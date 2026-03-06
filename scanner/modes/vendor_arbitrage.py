import sys

from scanner.api import universalis
from scanner.data.seeds import get_vendor_items, get_vendor_seed_ids
from scanner.output import print_header, print_vendor_result


def scan(
    dc: str,
    world: str | None = None,
    no_cache: bool = False,
    allow_stale: bool = False,
    min_markup: float = 50,
    min_velocity: float = 1.0,
) -> list[dict]:
    vendor_items = get_vendor_items()
    seed_ids = list(vendor_items.keys())

    price_region = world or dc
    prices = universalis.fetch_prices(seed_ids, price_region, no_cache=no_cache, allow_stale=allow_stale)

    results = []
    for item_id in seed_ids:
        vendor_info = vendor_items.get(item_id)
        if not vendor_info or vendor_info["price"] <= 0:
            continue

        npc_price = vendor_info["price"]
        price_data = prices.get(item_id)
        if not price_data or price_data.avg_sale_price <= 0:
            continue

        mb_price = price_data.avg_sale_price
        mb_effective = mb_price * 0.95

        if mb_effective <= npc_price:
            continue

        markup = ((mb_effective - npc_price) / npc_price) * 100
        velocity = price_data.nq_sale_velocity
        daily_profit = (mb_effective - npc_price) * velocity

        if markup >= min_markup and velocity >= min_velocity:
            results.append({
                "name": vendor_info["name"],
                "item_id": item_id,
                "npc_price": npc_price,
                "mb_price": mb_price,
                "markup_pct": markup,
                "velocity": velocity,
                "daily_profit": daily_profit,
                "is_stale": price_data.is_stale,
                "price_data": price_data,
            })

    results.sort(key=lambda r: r["daily_profit"], reverse=True)
    return results


def run(
    dc: str,
    world: str | None = None,
    no_cache: bool = False,
    allow_stale: bool = False,
    min_markup: float = 50,
    min_velocity: float = 1.0,
    show_worlds: bool = False,
):
    header = f"Vendor Arbitrage Scan — {dc} DC"
    if world:
        header += f" / {world}"
    print_header(header)

    results = scan(dc=dc, world=world, no_cache=no_cache, allow_stale=allow_stale,
                   min_markup=min_markup, min_velocity=min_velocity)

    if not results:
        print("\n  No vendor arbitrage opportunities found with current filters.")
        print(f"  (min markup: {min_markup}%, min velocity: {min_velocity}/day)")
        return

    print(f"\n  Found {len(results)} opportunities:\n")
    for r in results:
        print_vendor_result(
            name=r["name"],
            item_id=r["item_id"],
            npc_price=r["npc_price"],
            mb_price=r["mb_price"],
            markup_pct=r["markup_pct"],
            velocity=r["velocity"],
            daily_profit=r["daily_profit"],
            is_stale=r["is_stale"],
        )
        if show_worlds and r["price_data"].listings:
            from scanner.output import gil
            world_prices: dict[str, int] = {}
            for listing in r["price_data"].listings:
                w = listing.world_name
                if w not in world_prices or listing.price_per_unit < world_prices[w]:
                    world_prices[w] = listing.price_per_unit
            sorted_worlds = sorted(world_prices.items(), key=lambda x: x[1])
            parts = [f"{w}: {gil(p)}" for w, p in sorted_worlds]
            print(f"    Worlds: {' | '.join(parts)}")
            print()
