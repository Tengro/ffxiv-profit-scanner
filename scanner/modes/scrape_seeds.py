import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from scanner.api import garland, universalis
from scanner.data.seeds import GC_SEAL_ITEMS

SEEDS_PATH = Path.home() / ".ffxiv-scanner" / "seeds.json"

TEAMCRAFT_SHOPS_URL = (
    "https://raw.githubusercontent.com/ffxiv-teamcraft/ffxiv-teamcraft/"
    "refs/heads/staging/libs/data/src/lib/json/shops.json"
)

# NPC price range for vendor arbitrage candidates
VENDOR_PRICE_MIN = 10
VENDOR_PRICE_MAX = 5000

# Search terms organized by category
SEARCH_TERMS = {
    "submersibles": [
        "whale-class", "shark-class", "unkiu-class",
        "coelacanth-class", "syldra-class",
        "modified whale-class", "modified shark-class",
        "modified unkiu-class", "modified coelacanth-class",
        "modified syldra-class",
    ],
    "airships": [
        "bronco-type hull", "bronco-type forecastle",
        "bronco-type aftcastle", "bronco-type rigging",
        "enterprise-type", "invincible-type",
        "invincible II-type", "odyssey-type",
        "tatanora-type", "viltgance-type",
    ],
    "housing_walls": [
        "arms supplier's wall", "outfitter's wall", "eatery wall",
        "riviera wall", "glade wall", "oasis wall",
        "cottage wall", "manor wall",
    ],
    "vendor_materials": [
        "steel rivets", "steel ingot", "iron rivets", "iron ingot",
        "cobalt ingot", "mythrite ingot", "darksteel ingot",
        "holy cedar lumber", "spruce lumber", "walnut lumber",
        "iron nails", "bomb ash", "growth formula",
        "titanium ingot", "adamantite ingot", "dark chestnut lumber",
        "cobalt joint plate", "cobalt rivets", "garlond steel",
        "rose gold ingot", "celestine", "wolfram ingot",
        "hardsilver ingot", "enchanted hardsilver ink",
        "galvanized garlond steel", "cryptomeria lumber",
        "pure titanium plate", "rhodonite",
    ],
}

# Item types from Garland search that indicate workshop items
WORKSHOP_TYPES = {56, 66, 90, 91, 92, 93, 103}


def _search_and_collect(search_terms: list[str], category: str) -> dict[int, dict]:
    """Search Garland for items matching the given terms."""
    items = {}
    for term in search_terms:
        print(f"    Searching: {term}...")
        try:
            results = garland.search_items(term)
            for r in results:
                item_id = r["id"]
                # Skip non-numeric IDs (draft items etc.)
                if not isinstance(item_id, int):
                    try:
                        item_id = int(item_id)
                    except (ValueError, TypeError):
                        continue
                if item_id not in items:
                    items[item_id] = {
                        "id": item_id,
                        "name": r["name"],
                        "search_category": category,
                    }
        except Exception as e:
            print(f"      Warning: Search failed for '{term}': {e}", file=sys.stderr)
    return items


def _validate_and_classify(
    candidates: dict[int, dict],
    category: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Fetch full item data and classify into workshop, vendor, craftable."""
    workshop = []
    vendor = []
    craftable = []

    for item_id, info in candidates.items():
        try:
            item = garland.fetch_item(item_id, no_cache=False)
        except Exception as e:
            print(f"      Warning: Failed to fetch {info['name']} ({item_id}): {e}",
                  file=sys.stderr)
            continue

        entry = {"id": item_id, "name": item.name}

        if item.is_fc_workshop:
            workshop.append(entry)
        elif item.npc_price > 0 and not item.is_craftable and item_id not in GC_SEAL_ITEMS:
            entry["npc_price"] = item.npc_price
            vendor.append(entry)
        elif item.is_craftable and not item.is_fc_workshop:
            craftable.append(entry)
        elif item.npc_price > 0 and item.is_craftable and item_id not in GC_SEAL_ITEMS:
            # Items that are both craftable and NPC-sold (add to vendor with price)
            entry["npc_price"] = item.npc_price
            vendor.append(entry)

    return workshop, vendor, craftable


def scan(dc: str, no_cache: bool = False, on_progress: callable = None) -> dict:
    """Discover items and return a seeds dict. Does NOT save to disk."""
    def _progress(phase, msg):
        if on_progress:
            on_progress(phase, 3, msg)

    all_workshop = []
    all_vendor = []
    all_craftable = []

    # Phase 1: Search and validate workshop items
    _progress(1, "Discovering workshop items...")
    for category in ["submersibles", "airships", "housing_walls"]:
        candidates = _search_and_collect(SEARCH_TERMS[category], category)
        workshop, vendor, craftable = _validate_and_classify(candidates, category)
        for item in workshop:
            item["subcategory"] = category
        all_workshop.extend(workshop)
        all_craftable.extend(craftable)

    # Phase 2: Comprehensive vendor discovery via Teamcraft data
    _progress(2, "Discovering NPC vendor items (Teamcraft)...")
    try:
        tc_vendor_items = _fetch_teamcraft_vendor_items()
        workshop_ids = {item["id"] for item in all_workshop}
        tc_vendor_items = {
            k: v for k, v in tc_vendor_items.items()
            if k not in workshop_ids
        }
        profitable_vendors = _check_vendor_velocity(tc_vendor_items, dc, no_cache)
        _progress(2, f"Resolving names for {len(profitable_vendors)} vendor items...")
        for vendor_item in profitable_vendors:
            try:
                item = garland.fetch_item(vendor_item["id"], no_cache=False)
                vendor_item["name"] = item.name
            except Exception:
                vendor_item["name"] = f"Item {vendor_item['id']}"
        all_vendor.extend(profitable_vendors)
    except Exception as e:
        _progress(2, f"Teamcraft failed, falling back to Garland search...")
        candidates = _search_and_collect(SEARCH_TERMS["vendor_materials"], "vendor")
        _, vendor, craftable = _validate_and_classify(candidates, "vendor")
        all_vendor.extend(vendor)
        all_craftable.extend(craftable)

    # Deduplicate
    seen = set()
    all_workshop = _dedup(all_workshop, seen)
    all_vendor = _dedup(all_vendor, seen)
    all_craftable = _dedup(all_craftable, seen)

    # Phase 3: Check Universalis velocity for craftable items
    _progress(3, f"Checking velocity for {len(all_craftable)} craftable items...")
    popular = []
    if all_craftable:
        craft_ids = [item["id"] for item in all_craftable]
        try:
            prices = universalis.fetch_prices(craft_ids, dc, no_cache=no_cache)
            for item in all_craftable:
                price_data = prices.get(item["id"])
                if price_data and price_data.nq_sale_velocity >= 0.5:
                    item["velocity"] = round(price_data.nq_sale_velocity, 1)
                    popular.append(item)
        except Exception:
            pass

    # Organize workshop items by subcategory
    workshop_by_sub = {}
    for item in all_workshop:
        sub = item.pop("subcategory", "other")
        workshop_by_sub.setdefault(sub, []).append(
            {"id": item["id"], "name": item["name"]}
        )

    gc_seal_list = [
        {"id": item_id, "name": info["name"], "seals": info["seals"]}
        for item_id, info in GC_SEAL_ITEMS.items()
    ]

    seeds = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "workshop": workshop_by_sub,
        "vendor": [{"id": v["id"], "name": v["name"], "npc_price": v.get("npc_price", 0)}
                   for v in all_vendor],
        "gc_seal": gc_seal_list,
        "popular_crafts": [{"id": p["id"], "name": p["name"]} for p in popular],
    }

    _progress(3, "Done")
    return seeds


def save_seeds(seeds: dict):
    """Save seeds dict to disk."""
    SEEDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEDS_PATH.write_text(json.dumps(seeds, indent=2))


def run(dc: str, no_cache: bool = False):
    print("\n" + "=" * 60)
    print("  Seed Scraper — Discovering items via Garland Tools")
    print("=" * 60)

    def _print_progress(phase, total, msg):
        print(f"\n  Phase {phase}/{total}: {msg}")

    seeds = scan(dc=dc, no_cache=no_cache, on_progress=_print_progress)
    save_seeds(seeds)

    # Summary
    workshop_by_sub = seeds.get("workshop", {})
    total_workshop = sum(len(v) for v in workshop_by_sub.values())
    print(f"\n  {'=' * 50}")
    print(f"  Saved to: {SEEDS_PATH}")
    print(f"  Workshop items:  {total_workshop}")
    for sub, items in workshop_by_sub.items():
        print(f"    {sub}: {len(items)}")
    print(f"  Vendor items:    {len(seeds.get('vendor', []))}")
    print(f"  GC seal items:   {len(seeds.get('gc_seal', []))}")
    print(f"  Popular crafts:  {len(seeds.get('popular_crafts', []))}")
    print()


def _fetch_teamcraft_vendor_items() -> dict[int, int]:
    """Download Teamcraft shops.json and extract all gil-sold items.

    Returns {item_id: npc_price} for items in the VENDOR_PRICE_MIN..MAX range.
    """
    resp = requests.get(TEAMCRAFT_SHOPS_URL, timeout=30)
    resp.raise_for_status()
    shops = resp.json()

    gil_items: dict[int, int] = {}
    for shop in shops:
        if shop.get("type") != "GilShop":
            continue
        for trade in shop.get("trades", []):
            currencies = trade.get("currencies", [])
            items = trade.get("items", [])
            if len(currencies) == 1 and currencies[0].get("id") == 1:
                price = currencies[0].get("amount", 0)
                for item in items:
                    item_id = item.get("id")
                    if item_id and price > 0:
                        if item_id not in gil_items or price < gil_items[item_id]:
                            gil_items[item_id] = price

    # Filter to price range
    filtered = {
        item_id: price
        for item_id, price in gil_items.items()
        if VENDOR_PRICE_MIN <= price <= VENDOR_PRICE_MAX
        and item_id not in GC_SEAL_ITEMS
    }
    return filtered


def _check_vendor_velocity(
    vendor_items: dict[int, int],
    dc: str,
    no_cache: bool,
    min_velocity: float = 0.5,
) -> list[dict]:
    """Batch-check Universalis for vendor items with sales activity."""
    item_ids = list(vendor_items.keys())
    prices = universalis.fetch_prices(item_ids, dc, no_cache=no_cache, listings=0, entries=5)

    profitable = []
    for item_id, price in vendor_items.items():
        price_data = prices.get(item_id)
        if not price_data:
            continue
        if price_data.nq_sale_velocity < min_velocity:
            continue
        mb_price = price_data.avg_sale_price
        if mb_price <= 0:
            continue
        mb_effective = mb_price * 0.95
        if mb_effective <= price:
            continue
        markup = ((mb_effective - price) / price) * 100
        if markup < 20:
            continue
        profitable.append({
            "id": item_id,
            "npc_price": price,
            "mb_price": round(mb_price),
            "markup_pct": round(markup),
            "velocity": round(price_data.nq_sale_velocity, 1),
        })

    profitable.sort(key=lambda x: (x["markup_pct"] * x["velocity"]), reverse=True)
    return profitable


def _dedup(items: list[dict], seen: set) -> list[dict]:
    result = []
    for item in items:
        if item["id"] not in seen:
            seen.add(item["id"])
            result.append(item)
    return result
