import sys

from scanner.api import garland, universalis
from scanner.api.universalis import fetch_prices_lightweight
from scanner.output import print_header, print_gather_result


def scan(
    dc: str,
    world: str | None = None,
    no_cache: bool = False,
    allow_stale: bool = False,
    min_price: float = 100,
    min_velocity: float = 1.0,
    min_level: int = 0,
    btn_level: int = 0,
    fsh_level: int = 0,
    sort_by: str = "gil_per_day",
    on_progress: callable = None,
) -> list[dict]:
    """Find profitable gathering opportunities.

    Uses Garland node browse to find gatherable items first (fast),
    then fetches prices only for those items from Universalis.

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

    # Phase 1: Get gatherable items from Garland (node-first approach)
    _progress(1, "Scanning gathering nodes...")
    gather_items = garland.fetch_gathering_items(
        job_levels,
        no_cache=no_cache,
        on_progress=lambda msg: _progress(1, msg),
    )
    if not gather_items:
        _progress(1, "No gatherable items found for selected jobs/levels")
        return []

    _progress(1, f"Found {len(gather_items)} gatherable items, fetching prices...")

    # Phase 2: Fetch prices from Universalis (only for gatherable items)
    item_ids = [g["item_id"] for g in gather_items]
    _progress(2, f"Fetching prices for {len(item_ids)} items...")

    price_data = fetch_prices_lightweight(
        item_ids, dc, no_cache=no_cache, allow_stale=allow_stale,
        on_batch=lambda done, total: _progress(2, f"Fetching prices ({done}/{total} batches)..."),
    )

    # Build results
    results = []
    for g in gather_items:
        item_id = g["item_id"]
        mdata = price_data.get(item_id)
        if not mdata:
            continue

        avg_price = mdata.get("averagePrice", 0)
        velocity = mdata.get("regularSaleVelocity", 0)
        if avg_price < min_price or velocity < min_velocity:
            continue

        gil_per_day = avg_price * 0.95 * velocity

        results.append({
            "item_id": item_id,
            "name": g["name"],
            "job": g["job"],
            "level": g["level"],
            "location": g["location"],
            "is_timed": g["is_timed"],
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
            result_ids, world, no_cache=no_cache, allow_stale=allow_stale,
            listings=5, entries=20,
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
    allow_stale: bool = False,
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
        dc=dc, world=world, no_cache=no_cache, allow_stale=allow_stale,
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
