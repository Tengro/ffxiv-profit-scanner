import sys

from scanner.api import garland, universalis
from scanner.data.seeds import get_all_workshop_ids
from scanner.pricing import MarginResult, calculate_margin
from scanner.output import print_margin_result, print_header


def scan(
    dc: str,
    world: str | None = None,
    item_ids: list[int] | None = None,
    category: str | None = None,
    gc_seals_free: bool = False,
    no_cache: bool = False,
    allow_stale: bool = False,
    min_margin: float = 0,
    sort_by: str = "profit_per_day",
) -> list[MarginResult]:
    # Determine item IDs to scan
    if item_ids:
        scan_ids = item_ids
    elif category == "workshop" or category is None:
        scan_ids = get_all_workshop_ids()
    else:
        return []

    # Fetch all Garland items
    garland_items: dict[int, garland.GarlandItem] = {}
    all_ingredient_ids: set[int] = set()

    for item_id in scan_ids:
        try:
            item = garland.fetch_item(item_id, no_cache=no_cache)
            garland_items[item_id] = item
            for ing in item.ingredients:
                all_ingredient_ids.add(ing.item_id)
                if ing.has_recipe and ing.item_id not in garland_items:
                    try:
                        sub_item = garland.fetch_item(ing.item_id, no_cache=no_cache)
                        garland_items[ing.item_id] = sub_item
                        for sub_ing in sub_item.ingredients:
                            all_ingredient_ids.add(sub_ing.item_id)
                    except Exception:
                        pass
        except Exception as e:
            print(f"  Warning: Failed to fetch item {item_id}: {e}", file=sys.stderr)

    # Batch fetch DC-wide prices for all items + ingredients
    all_price_ids = list(set(scan_ids) | all_ingredient_ids)
    prices = universalis.fetch_prices(all_price_ids, dc, no_cache=no_cache, allow_stale=allow_stale)

    # Fetch world-specific prices for finished items
    world_prices = None
    if world:
        world_prices = universalis.fetch_prices(
            scan_ids, world, no_cache=no_cache, allow_stale=allow_stale,
            listings=5, entries=20,
        )

    # Calculate margins
    results: list[MarginResult] = []
    for item_id in scan_ids:
        item = garland_items.get(item_id)
        if not item or not item.is_craftable:
            continue
        result = calculate_margin(
            item, prices, garland_items, gc_seals_free,
            world_prices=world_prices,
        )
        if result and result.margin_pct >= min_margin:
            results.append(result)

    # Sort
    if sort_by == "margin_pct":
        results.sort(key=lambda r: r.margin_pct, reverse=True)
    else:
        results.sort(key=lambda r: r.profit_per_day, reverse=True)

    return results


def run(
    dc: str,
    world: str | None = None,
    item_ids: list[int] | None = None,
    category: str | None = None,
    gc_seals_free: bool = False,
    no_cache: bool = False,
    allow_stale: bool = False,
    min_margin: float = 0,
    sort_by: str = "profit_per_day",
    show_worlds: bool = False,
):
    header = f"Craft Scan — {dc} DC"
    if world:
        header += f" / {world}"
    print_header(header)

    results = scan(
        dc=dc, world=world, item_ids=item_ids, category=category,
        gc_seals_free=gc_seals_free, no_cache=no_cache, allow_stale=allow_stale,
        min_margin=min_margin, sort_by=sort_by,
    )

    if not results:
        print("\n  No profitable items found with current filters.")
        return

    print(f"\n  Found {len(results)} profitable items:\n")
    for result in results:
        print_margin_result(result, show_worlds=show_worlds)
