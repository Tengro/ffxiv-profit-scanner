"""Seal arbitrage scan — find the best gil-per-seal conversion rate.

Identifies tradeable items purchasable with GC seals that sell well on the MB.
Shows seal cost, MB price, gil-per-seal ratio, and velocity.
"""

import requests

from scanner.api import garland, universalis
from scanner.output import print_header, print_seal_result

MARKETABLE_URL = "https://universalis.app/api/v2/marketable"


def scan(
    dc: str,
    world: str | None = None,
    no_cache: bool = False,
    allow_stale: bool = False,
    min_velocity: float = 0.5,
    sort_by: str = "gil_per_seal",
    on_progress: callable = None,
) -> list[dict]:
    """Find best GC seal → gil conversions.

    Flow:
    1. Get all marketable item IDs from Universalis
    2. Lightweight price scan (world-specific) → filter by velocity only
    3. Check Garland for GC seal trade shops
    4. Full price fetch (outlier-resistant)
    5. Calculate gil-per-seal ratio, sort and return
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

    # Phase 2: Lightweight price scan — velocity filter only
    price_target = world or dc
    _progress(2, f"Scanning {price_target} prices ({len(all_item_ids)} items)...")

    market_data = universalis.fetch_prices_lightweight(
        all_item_ids, price_target, no_cache=no_cache, allow_stale=allow_stale,
        on_batch=lambda done, total: _progress(2, f"Scanning prices ({done}/{total} batches)..."),
    )

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

    # Phase 3: Check which candidates are GC seal items
    _progress(3, f"Checking for GC seal items ({len(candidates)} candidates)...")
    seal_items = garland.check_seal_items(
        candidates, no_cache=no_cache,
        on_progress=lambda msg: _progress(3, msg),
    )
    _progress(3, f"{len(seal_items)} seal items found")

    if not seal_items:
        _progress(5, "No GC seal items found")
        return []

    # Phase 4: Full price fetch with outlier-resistant averaging
    seal_ids = list(seal_items.keys())
    _progress(4, f"Fetching detailed prices for {len(seal_ids)} items...")
    price_data = universalis.fetch_prices(
        seal_ids, price_target, no_cache=no_cache, allow_stale=allow_stale,
        listings=5, entries=20,
    )

    # Build results
    results = []
    for item_id, seal_info in seal_items.items():
        pd = price_data.get(item_id)
        if not pd:
            continue

        avg_price = pd.avg_sale_price
        velocity = pd.nq_sale_velocity
        if avg_price <= 0 or velocity < min_velocity:
            continue

        mb_effective = avg_price * 0.95  # After 5% tax
        seal_cost = seal_info["seal_cost"]
        gil_per_seal = mb_effective / seal_cost if seal_cost > 0 else 0
        daily_profit = mb_effective * velocity

        results.append({
            "item_id": item_id,
            "name": seal_info["name"],
            "seal_cost": seal_cost,
            "mb_price": avg_price,
            "gil_per_seal": gil_per_seal,
            "velocity": velocity,
            "daily_profit": daily_profit,
            "is_stale": pd.is_stale,
            "last_updated": pd.last_upload_time,
        })

    _progress(4, f"{len(results)} items pass all filters")

    # Phase 5: Sort
    if sort_by == "mb_price":
        results.sort(key=lambda r: r["mb_price"], reverse=True)
    elif sort_by == "velocity":
        results.sort(key=lambda r: r["velocity"], reverse=True)
    elif sort_by == "daily_profit":
        results.sort(key=lambda r: r["daily_profit"], reverse=True)
    else:
        results.sort(key=lambda r: r["gil_per_seal"], reverse=True)

    _progress(5, f"Done — {len(results)} seal arbitrage opportunities")
    return results


def run(
    dc: str,
    world: str | None = None,
    no_cache: bool = False,
    allow_stale: bool = False,
    min_velocity: float = 0.5,
    sort_by: str = "gil_per_seal",
):
    header = f"Seal Arbitrage Scan — {dc} DC"
    if world:
        header += f" / {world}"
    print_header(header)

    def _print_progress(phase, total, msg):
        print(f"  Phase {phase}/{total}: {msg}")

    results = scan(
        dc=dc, world=world, no_cache=no_cache, allow_stale=allow_stale,
        min_velocity=min_velocity, sort_by=sort_by,
        on_progress=_print_progress,
    )

    if not results:
        print("\n  No seal arbitrage opportunities found with current filters.")
        return

    print(f"\n  Found {len(results)} opportunities:\n")
    for r in results:
        print_seal_result(
            name=r["name"],
            item_id=r["item_id"],
            seal_cost=r["seal_cost"],
            mb_price=r["mb_price"],
            gil_per_seal=r["gil_per_seal"],
            velocity=r["velocity"],
            daily_profit=r["daily_profit"],
            is_stale=r["is_stale"],
        )
