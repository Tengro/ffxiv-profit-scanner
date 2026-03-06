import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from scanner.api import garland, universalis
from scanner.api.universalis import _request_with_retry
from scanner.data.seeds import GC_SEAL_ITEMS
from scanner.modes.scrape_seeds import SEEDS_PATH
from scanner.pricing import calculate_margin
from scanner.output import print_margin_result, print_header

MARKETABLE_URL = "https://universalis.app/api/v2/marketable"


def scan(
    dc: str,
    world: str | None = None,
    no_cache: bool = False,
    allow_stale: bool = False,
    min_price: float = 50000,
    min_velocity: float = 0.5,
    min_margin: float = 0,
    sort_by: str = "profit_per_day",
    on_progress: callable = None,
) -> list:
    """Run market discovery. Returns list of MarginResult.

    on_progress(phase, total_phases, message) is called for status updates.
    """
    def _progress(phase, msg):
        if on_progress:
            on_progress(phase, 5, msg)

    # Phase 1: Get all marketable item IDs
    _progress(1, "Fetching marketable items list...")
    resp = requests.get(MARKETABLE_URL, timeout=30)
    resp.raise_for_status()
    all_item_ids = resp.json()
    _progress(1, f"{len(all_item_ids)} marketable items")

    # Phase 2: Batch-query Universalis for velocity + price
    total_batches = len(all_item_ids) // 100 + 1
    _progress(2, f"Scanning prices (0/{total_batches} batches)...")
    market_data = _batch_fetch_lightweight(
        all_item_ids, dc, no_cache=no_cache, allow_stale=allow_stale,
        on_batch=lambda done, total: _progress(2, f"Scanning prices ({done}/{total} batches)..."),
    )

    candidates = {}
    for item_id, data in market_data.items():
        avg_price = data.get("averagePrice", 0)
        velocity = data.get("regularSaleVelocity", 0)
        if avg_price >= min_price and velocity >= min_velocity:
            candidates[item_id] = data

    _progress(2, f"{len(candidates)} candidates found")

    # Phase 3: Check which candidates are craftable
    _progress(3, f"Checking recipes for {len(candidates)} candidates...")
    garland_items = {}
    all_ingredient_ids = set()
    craftable_ids = []

    for i, item_id in enumerate(candidates):
        if (i + 1) % 10 == 0:
            _progress(3, f"Checking recipes... {i + 1}/{len(candidates)}")
        try:
            item = garland.fetch_item(item_id, no_cache=no_cache)
            if item.is_craftable:
                garland_items[item_id] = item
                craftable_ids.append(item_id)
                for ing in item.ingredients:
                    all_ingredient_ids.add(ing.item_id)
                    if ing.has_recipe and ing.item_id not in garland_items:
                        try:
                            sub = garland.fetch_item(ing.item_id, no_cache=no_cache)
                            garland_items[ing.item_id] = sub
                            for sub_ing in sub.ingredients:
                                all_ingredient_ids.add(sub_ing.item_id)
                        except Exception:
                            pass
        except Exception:
            pass

    _progress(3, f"{len(craftable_ids)} craftable items found")

    if not craftable_ids:
        return []

    # Phase 4: Fetch full prices
    all_price_ids = list(set(craftable_ids) | all_ingredient_ids)
    _progress(4, f"Fetching detailed prices for {len(all_price_ids)} items...")

    prices = universalis.fetch_prices(
        all_price_ids, dc, no_cache=no_cache, allow_stale=allow_stale, entries=20,
    )

    world_prices = None
    if world:
        _progress(4, f"Fetching {world} prices...")
        world_prices = universalis.fetch_prices(
            craftable_ids, world, no_cache=no_cache, allow_stale=allow_stale,
            listings=5, entries=20,
        )

    # Phase 5: Calculate margins
    _progress(5, "Calculating margins...")
    results = []
    for item_id in craftable_ids:
        item = garland_items.get(item_id)
        if not item:
            continue
        result = calculate_margin(
            item, prices, garland_items, gc_seals_free=False,
            world_prices=world_prices,
        )
        if result and result.margin_pct >= min_margin and result.margin > 0:
            results.append(result)

    if sort_by == "margin_pct":
        results.sort(key=lambda r: r.margin_pct, reverse=True)
    else:
        results.sort(key=lambda r: r.profit_per_day, reverse=True)

    # Save discovered items to seeds
    _save_discovered(craftable_ids, garland_items)

    _progress(5, f"Done — {len(results)} profitable items")
    return results


def run(
    dc: str,
    world: str | None = None,
    no_cache: bool = False,
    allow_stale: bool = False,
    min_price: float = 50000,
    min_velocity: float = 0.5,
    min_margin: float = 0,
    sort_by: str = "profit_per_day",
    show_worlds: bool = False,
):
    header = f"Market Discovery — {dc} DC"
    if world:
        header += f" / {world}"
    print_header(header)

    def _print_progress(phase, total, msg):
        print(f"  Phase {phase}/{total}: {msg}")

    results = scan(
        dc=dc, world=world, no_cache=no_cache, allow_stale=allow_stale,
        min_price=min_price, min_velocity=min_velocity,
        min_margin=min_margin, sort_by=sort_by,
        on_progress=_print_progress,
    )

    if not results:
        print("\n  No profitable craftable items found.")
        return

    print(f"\n  Found {len(results)} profitable items:\n")
    for result in results:
        print_margin_result(result, show_worlds=show_worlds)


def _batch_fetch_lightweight(
    item_ids: list[int],
    dc: str,
    no_cache: bool = False,
    allow_stale: bool = False,
    on_batch: callable = None,
) -> dict[int, dict]:
    """Fetch just averagePrice + velocity for all items. Cached per-item."""
    from scanner import cache

    result = {}
    to_fetch = []

    # Check cache first
    if not no_cache:
        for item_id in item_ids:
            cached = cache.get("universalis", f"lite_{dc}_{item_id}", allow_stale=allow_stale)
            if cached is not None:
                result[item_id] = cached
            else:
                to_fetch.append(item_id)
    else:
        to_fetch = list(item_ids)

    if not to_fetch:
        if on_batch:
            on_batch(1, 1)
        return result

    total_batches = (len(to_fetch) + 99) // 100
    for i in range(0, len(to_fetch), 100):
        batch = to_fetch[i:i + 100]
        batch_num = i // 100 + 1
        ids_str = ",".join(str(x) for x in batch)
        try:
            resp = _request_with_retry(
                f"https://universalis.app/api/v2/{dc}/{ids_str}",
                params={"listings": 0, "entries": 1},
            )
            data = resp.json()
            if len(batch) == 1:
                result[batch[0]] = data
                if not no_cache:
                    cache.put("universalis", f"lite_{dc}_{batch[0]}", data)
            else:
                for k, v in data.get("items", {}).items():
                    item_id = int(k)
                    result[item_id] = v
                    if not no_cache:
                        cache.put("universalis", f"lite_{dc}_{item_id}", v)
        except requests.exceptions.Timeout:
            print(f"  Warning: Batch {batch_num}/{total_batches} timed out after retries",
                  file=sys.stderr)
        except requests.exceptions.HTTPError as e:
            print(f"  Warning: Batch {batch_num}/{total_batches} failed HTTP {e.response.status_code} after retries",
                  file=sys.stderr)
        except Exception as e:
            print(f"  Warning: Batch {batch_num}/{total_batches} failed: {e}",
                  file=sys.stderr)
        if on_batch and batch_num % 5 == 0:
            on_batch(batch_num, total_batches)
        time.sleep(0.25)
    return result


def _save_discovered(
    craftable_ids: list[int],
    garland_items: dict[int, garland.GarlandItem],
):
    """Append discovered craftable items to seeds.json."""
    if not SEEDS_PATH.exists():
        return
    try:
        seeds = json.loads(SEEDS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return

    existing_ids = set()
    for sub in seeds.get("workshop", {}).values():
        for item in sub:
            existing_ids.add(item["id"])
    for item in seeds.get("popular_crafts", []):
        existing_ids.add(item["id"])
    for item in seeds.get("discovered", []):
        existing_ids.add(item["id"])

    new_items = []
    for item_id in craftable_ids:
        if item_id not in existing_ids:
            item = garland_items.get(item_id)
            if item:
                new_items.append({"id": item_id, "name": item.name})

    if new_items:
        seeds.setdefault("discovered", []).extend(new_items)
        seeds["last_discovery"] = datetime.now(timezone.utc).isoformat()
        SEEDS_PATH.write_text(json.dumps(seeds, indent=2))
        print(f"\n  Saved {len(new_items)} newly discovered items to seeds.json")
