from scanner.pricing import MarginResult, IngredientCost


def gil(amount: float) -> str:
    if amount >= 0:
        return f"{amount:,.0f}"
    return f"-{abs(amount):,.0f}"


def print_header(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_margin_result(
    result: MarginResult,
    show_worlds: bool = False,
    prices: dict | None = None,
):
    stale = " [STALE DATA]" if result.is_stale else ""

    print(f"=== {result.name} (ID: {result.item_id}) ==={stale}")
    print(f"  MB Price (avg sale):  {gil(result.mb_price):>15} gil")
    print(f"  Craft Cost:           {gil(result.craft_cost):>15} gil")
    print(f"  Margin:               {gil(result.margin):>15} gil ({result.margin_pct:.0f}%)")
    print(f"  Sales/day:            {result.sale_velocity:>15.1f}")
    print(f"  Est. daily profit:    {gil(result.profit_per_day):>15} gil")
    print()
    print("  Components:")
    for ing in result.ingredient_costs:
        _print_ingredient(ing)
        if show_worlds and prices:
            _print_world_listings(ing.item_id, prices)
    print()


def _print_ingredient(ing: IngredientCost):
    source_tag = ing.source.upper()
    total = gil(ing.total_cost)
    ppu = gil(ing.price_per_unit)
    print(f"    {ing.name:<25} x{ing.amount:<4} @ {ppu:>8} ea ({source_tag:<12}) = {total:>10}")

    if ing.craft_alternative is not None and ing.craft_savings_pct is not None:
        alt = gil(ing.craft_alternative)
        print(f"    [!] {ing.name} is also craftable:")
        print(f"        Craft cost: ~{alt} ea vs MB {gil(ing.price_per_unit)} ea ({ing.craft_savings_pct:.0f}% savings)")


def _print_world_listings(item_id: int, prices: dict):
    from scanner.api.universalis import PriceData
    price_data: PriceData | None = prices.get(item_id)
    if not price_data or not price_data.listings:
        return
    # Group by world, show cheapest per world
    world_prices: dict[str, int] = {}
    for listing in price_data.listings:
        world = listing.world_name
        if world not in world_prices or listing.price_per_unit < world_prices[world]:
            world_prices[world] = listing.price_per_unit

    if len(world_prices) <= 1:
        return

    sorted_worlds = sorted(world_prices.items(), key=lambda x: x[1])
    parts = [f"{w}: {gil(p)}" for w, p in sorted_worlds[:5]]
    print(f"      Worlds: {' | '.join(parts)}")


def print_vendor_result(
    name: str,
    item_id: int,
    npc_price: float,
    mb_price: float,
    markup_pct: float,
    velocity: float,
    daily_profit: float,
    is_stale: bool,
):
    stale = " [STALE DATA]" if is_stale else ""
    print(f"  {name:<30} (ID: {item_id}){stale}")
    print(f"    NPC: {gil(npc_price):>10} → MB: {gil(mb_price):>10}  ({markup_pct:>6.0f}% markup)")
    print(f"    Sales/day: {velocity:.1f}  |  Est. daily profit: {gil(daily_profit)} gil")
    print()


def print_cross_world_result(
    name: str,
    item_id: int,
    cheap_world: str,
    cheap_price: int,
    cheap_qty: int,
    expensive_world: str,
    expensive_price: float,
    spread_pct: float,
    net_profit_per_unit: float,
    is_stale: bool,
):
    stale = " [STALE DATA]" if is_stale else ""
    thin = " [THIN MARKET]" if cheap_qty < 10 else ""
    print(f"  {name:<30} (ID: {item_id}){stale}{thin}")
    print(f"    Buy: {cheap_world} @ {gil(cheap_price)} (qty: {cheap_qty})")
    print(f"    Sell: {expensive_world} @ {gil(expensive_price)}")
    print(f"    Spread: {spread_pct:.0f}%  |  Net profit/unit: {gil(net_profit_per_unit)} gil (after 5% tax)")
    print()


def print_gather_result(
    name: str,
    item_id: int,
    job: str,
    level: int,
    location: str,
    is_timed: bool,
    mb_price: float,
    velocity: float,
    gil_per_day: float,
    is_stale: bool,
):
    stale = " [STALE]" if is_stale else ""
    timed = " [T]" if is_timed else ""
    print(f"  {name:<30} {job} Lv.{level:<3}{timed}{stale}")
    print(f"    Location: {location}")
    print(f"    MB Price: {gil(mb_price):>10}  |  Sales/day: {velocity:.1f}  |  Gil/day: {gil(gil_per_day)}")
    print()
