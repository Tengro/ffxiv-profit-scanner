import sys

from scanner.api import garland, universalis
from scanner.modes.discover import _batch_fetch_lightweight, MARKETABLE_URL
from scanner.output import print_header, print_gather_result

import requests


def scan(
    dc: str,
    world: str | None = None,
    no_cache: bool = False,
    min_price: float = 100,
    min_velocity: float = 1.0,
    min_level: int = 0,
    btn_level: int = 0,
    fsh_level: int = 0,
    sort_by: str = "gil_per_day",
    on_progress: callable = None,
) -> list[dict]:
    """Find profitable gathering opportunities.

    Level params: 0 = skip that job, >0 = show items up to that level.
    """
    def _progress(phase, msg):
        if on_progress:
            on_progress(phase, 3, msg)

    # Build job filter from levels
    job_levels = {}
    if min_level > 0:
        job_levels["MIN"] = min_level
    if btn_level > 0:
        job_levels["BTN"] = btn_level
    if fsh_level > 0:
        job_levels["FSH"] = fsh_level

    if not job_levels:
        _progress(1, "No gathering jobs selected (all levels are 0)")
        return []

    # Phase 1: Get marketable items + prices (reuses cache from discover)
    _progress(1, "Fetching marketable items...")
    resp = requests.get(MARKETABLE_URL, timeout=30)
    resp.raise_for_status()
    all_item_ids = resp.json()

    total_batches = len(all_item_ids) // 100 + 1
    _progress(1, f"Scanning prices (0/{total_batches} batches)...")
    market_data = _batch_fetch_lightweight(
        all_item_ids, dc,
        on_batch=lambda done, total: _progress(1, f"Scanning prices ({done}/{total} batches)..."),
    )

    # Filter candidates by price and velocity
    candidates = []
    for item_id, data in market_data.items():
        avg_price = data.get("averagePrice", 0)
        velocity = data.get("regularSaleVelocity", 0)
        if avg_price >= min_price and velocity >= min_velocity:
            candidates.append(item_id)

    _progress(2, f"{len(candidates)} candidates, checking gathering data...")

    # Phase 2: Check Garland for gathering nodes
    # Use world-specific prices if available for more accurate revenue
    price_region = world or dc
    results = []
    for i, item_id in enumerate(candidates):
        if (i + 1) % 20 == 0:
            _progress(2, f"Checking items... {i + 1}/{len(candidates)}")
        try:
            item = garland.fetch_item(item_id, no_cache=no_cache)
        except Exception:
            continue

        if not item.is_gathered:
            continue

        # Find the best matching node for user's job levels
        best_node = None
        for node in item.gathering_nodes:
            if node.job not in job_levels:
                continue
            if node.level > job_levels[node.job]:
                continue
            if best_node is None or node.level < best_node.level:
                best_node = node

        if not best_node:
            continue

        # Get price data (from lightweight scan)
        mdata = market_data.get(item_id, {})
        avg_price = mdata.get("averagePrice", 0)
        velocity = mdata.get("regularSaleVelocity", 0)
        if avg_price <= 0 or velocity <= 0:
            continue

        gil_per_day = avg_price * 0.95 * velocity

        results.append({
            "item_id": item_id,
            "name": item.name,
            "job": best_node.job,
            "level": best_node.level,
            "location": best_node.name,
            "is_timed": best_node.is_timed,
            "mb_price": avg_price,
            "velocity": velocity,
            "gil_per_day": gil_per_day,
            "is_stale": False,
        })

    _progress(3, f"Found {len(results)} gathering opportunities")

    # Phase 3: Optionally refine prices with world-specific data
    if world and results:
        _progress(3, f"Fetching {world} prices...")
        result_ids = [r["item_id"] for r in results]
        world_prices = universalis.fetch_prices(
            result_ids, world, no_cache=no_cache, listings=5, entries=20,
        )
        for r in results:
            wp = world_prices.get(r["item_id"])
            if wp and wp.avg_sale_price > 0:
                r["mb_price"] = wp.avg_sale_price
                r["velocity"] = wp.nq_sale_velocity
                r["gil_per_day"] = wp.avg_sale_price * 0.95 * wp.nq_sale_velocity
                r["is_stale"] = wp.is_stale

    if sort_by == "mb_price":
        results.sort(key=lambda r: r["mb_price"], reverse=True)
    elif sort_by == "velocity":
        results.sort(key=lambda r: r["velocity"], reverse=True)
    else:
        results.sort(key=lambda r: r["gil_per_day"], reverse=True)

    _progress(3, f"Done — {len(results)} items")
    return results


def run(
    dc: str,
    world: str | None = None,
    no_cache: bool = False,
    min_price: float = 100,
    min_velocity: float = 1.0,
    min_level: int = 0,
    btn_level: int = 0,
    fsh_level: int = 0,
    sort_by: str = "gil_per_day",
):
    header = f"Gatherer Profit Scan — {dc} DC"
    if world:
        header += f" / {world}"
    jobs = []
    if min_level > 0:
        jobs.append(f"MIN {min_level}")
    if btn_level > 0:
        jobs.append(f"BTN {btn_level}")
    if fsh_level > 0:
        jobs.append(f"FSH {fsh_level}")
    if jobs:
        header += f" ({', '.join(jobs)})"
    print_header(header)

    def _print_progress(phase, total, msg):
        print(f"  Phase {phase}/{total}: {msg}")

    results = scan(
        dc=dc, world=world, no_cache=no_cache,
        min_price=min_price, min_velocity=min_velocity,
        min_level=min_level, btn_level=btn_level, fsh_level=fsh_level,
        sort_by=sort_by, on_progress=_print_progress,
    )

    if not results:
        print("\n  No gathering opportunities found with current filters.")
        return

    print(f"\n  Found {len(results)} opportunities:\n")
    for r in results:
        print_gather_result(
            name=r["name"],
            item_id=r["item_id"],
            job=r["job"],
            level=r["level"],
            location=r["location"],
            is_timed=r["is_timed"],
            mb_price=r["mb_price"],
            velocity=r["velocity"],
            gil_per_day=r["gil_per_day"],
            is_stale=r["is_stale"],
        )
