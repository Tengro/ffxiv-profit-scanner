"""Hunter scan — find profitable mob-drop materials to farm and sell.

Identifies items obtained by killing mobs (hides, horns, meat, bones, etc.)
using item-side detection: tradeable items with retainer hunting ventures
but no gathering nodes and no crafting recipe.

Works across all expansions — Garland mob data caps at L70, but the item
signals (ventures + !nodes + !craft) are universal.
"""

import requests

from scanner.api import garland, universalis
from scanner.output import print_header, print_hunter_result

MARKETABLE_URL = "https://universalis.app/api/v2/marketable"


def _detect_bargain(price_data, robust_avg: float) -> dict | None:
    """Same bargain detection as gather mode."""
    if not price_data or not price_data.listings or robust_avg <= 0:
        return None

    threshold = robust_avg / 3
    bargains = [
        l for l in price_data.listings
        if l.price_per_unit > 0 and l.price_per_unit < threshold
    ]
    if not bargains:
        return None

    cheapest = min(bargains, key=lambda l: l.price_per_unit)
    total_qty = sum(l.quantity for l in bargains)
    return {
        "price": cheapest.price_per_unit,
        "qty": total_qty,
        "world": cheapest.world_name,
        "discount_pct": round((1 - cheapest.price_per_unit / robust_avg) * 100),
    }


def scan(
    dc: str,
    world: str | None = None,
    no_cache: bool = False,
    allow_stale: bool = False,
    min_price: float = 100,
    min_velocity: float = 1.0,
    sort_by: str = "gil_per_day",
    on_progress: callable = None,
) -> list[dict]:
    """Find profitable mob-drop materials.

    Flow:
    1. Get all marketable item IDs from Universalis
    2. Lightweight price scan (world-specific) → filter by velocity only
    3. Check survivors against Garland → keep hunting materials
    4. Full price fetch (world-specific, outlier-resistant) → filter by price
    5. Sort and return
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

    # Phase 2: Lightweight price scan — velocity filter only (world-specific)
    price_target = world or dc
    _progress(2, f"Scanning {price_target} prices ({len(all_item_ids)} items)...")

    market_data = universalis.fetch_prices_lightweight(
        all_item_ids, price_target, no_cache=no_cache, allow_stale=allow_stale,
        on_batch=lambda done, total: _progress(2, f"Scanning prices ({done}/{total} batches)..."),
    )

    # Filter by velocity only — price filtering waits for outlier-resistant step 4
    velocity_key = "nqSaleVelocity"
    velocity_fallback = "regularSaleVelocity"
    candidates = []
    for item_id, data in market_data.items():
        vel = data.get(velocity_key, data.get(velocity_fallback, 0))
        if vel >= min_velocity:
            candidates.append(item_id)

    _progress(2, f"{len(candidates)} items pass velocity filter (>= {min_velocity}/day)")

    if not candidates:
        _progress(5, "No items found with sufficient velocity")
        return []

    # Phase 3: Check which candidates are hunting materials via Garland
    _progress(3, f"Identifying hunting materials ({len(candidates)} candidates)...")
    hunting_items = garland.check_hunting_items(
        candidates, no_cache=no_cache,
        on_progress=lambda msg: _progress(3, msg),
    )
    _progress(3, f"{len(hunting_items)} hunting materials identified")

    if not hunting_items:
        _progress(5, "No hunting materials found")
        return []

    # Phase 4: Full price fetch with outlier-resistant averaging
    hunter_ids = list(hunting_items.keys())
    _progress(4, f"Fetching detailed prices for {len(hunter_ids)} items...")
    price_data = universalis.fetch_prices(
        hunter_ids, price_target, no_cache=no_cache, allow_stale=allow_stale,
        listings=5, entries=20,
    )

    # Build results — now filter by price (outlier-resistant)
    results = []
    for item_id, name in hunting_items.items():
        pd = price_data.get(item_id)
        if not pd:
            continue

        avg_price = pd.avg_sale_price
        velocity = pd.nq_sale_velocity
        if avg_price < min_price or velocity < min_velocity:
            continue

        gil_per_day = avg_price * 0.95 * velocity
        bargain = _detect_bargain(pd, avg_price)

        results.append({
            "item_id": item_id,
            "name": name,
            "mb_price": avg_price,
            "velocity": velocity,
            "gil_per_day": gil_per_day,
            "is_stale": pd.is_stale,
            "last_updated": pd.last_upload_time,
            "bargain": bargain,
        })

    _progress(4, f"{len(results)} items pass all filters")

    # Phase 5: Sort
    if sort_by == "mb_price":
        results.sort(key=lambda r: r["mb_price"], reverse=True)
    elif sort_by == "velocity":
        results.sort(key=lambda r: r["velocity"], reverse=True)
    else:
        results.sort(key=lambda r: r["gil_per_day"], reverse=True)

    _progress(5, f"Done — {len(results)} hunting opportunities")
    return results


def run(
    dc: str,
    world: str | None = None,
    no_cache: bool = False,
    allow_stale: bool = False,
    min_price: float = 100,
    min_velocity: float = 1.0,
    sort_by: str = "gil_per_day",
):
    header = f"Hunter Scan — {dc} DC"
    if world:
        header += f" / {world}"
    print_header(header)

    def _print_progress(phase, total, msg):
        print(f"  Phase {phase}/{total}: {msg}")

    results = scan(
        dc=dc, world=world, no_cache=no_cache, allow_stale=allow_stale,
        min_price=min_price, min_velocity=min_velocity,
        sort_by=sort_by, on_progress=_print_progress,
    )

    if not results:
        print("\n  No hunting opportunities found with current filters.")
        return

    print(f"\n  Found {len(results)} opportunities:\n")
    for r in results:
        print_hunter_result(
            name=r["name"],
            item_id=r["item_id"],
            mb_price=r["mb_price"],
            velocity=r["velocity"],
            gil_per_day=r["gil_per_day"],
            is_stale=r["is_stale"],
            bargain=r.get("bargain"),
        )
