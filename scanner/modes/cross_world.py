import sys

from scanner.api import garland, universalis
from scanner.data.seeds import get_all_workshop_ids, get_vendor_items, get_vendor_seed_ids
from scanner.output import print_header, print_cross_world_result

TAX_RATE = 0.05


def scan(
    dc: str,
    item_ids: list[int] | None = None,
    category: str | None = None,
    no_cache: bool = False,
    min_spread: float = 50,
    min_velocity: float = 0.5,
) -> list[dict]:
    if item_ids:
        scan_ids = item_ids
    elif category == "workshop":
        scan_ids = get_all_workshop_ids()
    elif category == "vendor":
        scan_ids = get_vendor_seed_ids()
    else:
        scan_ids = list(set(get_all_workshop_ids() + get_vendor_seed_ids()))

    prices = universalis.fetch_prices(
        scan_ids, dc, no_cache=no_cache, listings=20, entries=20,
    )

    vendor_items = get_vendor_items()
    names: dict[int, str] = {}
    for item_id in scan_ids:
        if item_id in vendor_items:
            names[item_id] = vendor_items[item_id]["name"]

    results = []
    for item_id in scan_ids:
        price_data = prices.get(item_id)
        if not price_data or not price_data.listings:
            continue
        if price_data.nq_sale_velocity < min_velocity:
            continue

        cheapest = min(price_data.listings, key=lambda l: l.price_per_unit)
        cheap_world = cheapest.world_name
        cheap_price = cheapest.price_per_unit

        cheap_qty = sum(
            l.quantity for l in price_data.listings
            if l.world_name == cheap_world and l.price_per_unit <= cheap_price * 1.1
        )

        if not price_data.recent_sales:
            continue
        best_sale = max(price_data.recent_sales, key=lambda s: s["price"])
        expensive_world = best_sale["world_name"]
        expensive_price = best_sale["price"]

        if cheap_price <= 0:
            continue

        net_sell = expensive_price * (1 - TAX_RATE)
        net_profit = net_sell - cheap_price
        spread_pct = ((net_sell - cheap_price) / cheap_price) * 100

        if spread_pct < min_spread or net_profit <= 0:
            continue

        name = names.get(item_id, f"Item {item_id}")
        if name.startswith("Item "):
            try:
                item = garland.fetch_item(item_id, no_cache=no_cache)
                name = item.name
                names[item_id] = name
            except Exception:
                pass

        results.append({
            "name": name,
            "item_id": item_id,
            "cheap_world": cheap_world,
            "cheap_price": cheap_price,
            "cheap_qty": cheap_qty,
            "expensive_world": expensive_world,
            "expensive_price": expensive_price,
            "spread_pct": spread_pct,
            "net_profit": net_profit,
            "is_stale": price_data.is_stale,
        })

    results.sort(key=lambda r: r["spread_pct"], reverse=True)
    return results


def run(
    dc: str,
    item_ids: list[int] | None = None,
    category: str | None = None,
    no_cache: bool = False,
    min_spread: float = 50,
    min_velocity: float = 0.5,
    show_worlds: bool = False,
):
    print_header(f"Cross-World Spread Scan — {dc} DC")

    results = scan(dc=dc, item_ids=item_ids, category=category,
                   no_cache=no_cache, min_spread=min_spread,
                   min_velocity=min_velocity)

    if not results:
        print(f"\n  No cross-world spreads found above {min_spread}%.")
        return

    print(f"\n  Found {len(results)} opportunities:\n")
    for r in results:
        print_cross_world_result(
            name=r["name"],
            item_id=r["item_id"],
            cheap_world=r["cheap_world"],
            cheap_price=r["cheap_price"],
            cheap_qty=r["cheap_qty"],
            expensive_world=r["expensive_world"],
            expensive_price=r["expensive_price"],
            spread_pct=r["spread_pct"],
            net_profit_per_unit=r["net_profit"],
            is_stale=r["is_stale"],
        )
