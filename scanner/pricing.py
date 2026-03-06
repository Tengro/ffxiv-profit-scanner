from dataclasses import dataclass, field

from scanner.api.garland import GarlandItem, Ingredient
from scanner.api.universalis import PriceData
from scanner.data.seeds import CRYSTAL_CATEGORY, GC_SEAL_ITEMS

TAX_RATE = 0.05
GATHERED_THRESHOLD = 500  # MB price below this for no-recipe, no-NPC items = "gathered"


@dataclass
class IngredientCost:
    item_id: int
    name: str
    amount: int
    price_per_unit: float
    total_cost: float
    source: str  # "npc", "gc_seals", "gathered", "mb", "crystal"
    # If craftable, the alternative craft cost
    craft_alternative: float | None = None
    craft_savings_pct: float | None = None


@dataclass
class MarginResult:
    item_id: int
    name: str
    mb_price: float
    craft_cost: float
    margin: float
    margin_pct: float
    revenue: float
    sale_velocity: float
    profit_per_day: float
    is_stale: bool
    ingredient_costs: list[IngredientCost] = field(default_factory=list)


def resolve_ingredient_cost(
    ingredient: Ingredient,
    prices: dict[int, PriceData],
    garland_items: dict[int, GarlandItem],
    gc_seals_free: bool = False,
) -> IngredientCost:
    item_id = ingredient.item_id
    amount = ingredient.amount
    name = ingredient.name

    # Priority 1: GC seal items
    if item_id in GC_SEAL_ITEMS:
        if gc_seals_free:
            return IngredientCost(
                item_id=item_id, name=name, amount=amount,
                price_per_unit=0, total_cost=0, source="gc_seals",
            )
        # Fall through to MB price if not free
        price_data = prices.get(item_id)
        if price_data and price_data.avg_sale_price > 0:
            ppu = price_data.avg_sale_price
            return IngredientCost(
                item_id=item_id, name=name, amount=amount,
                price_per_unit=ppu, total_cost=ppu * amount, source="mb (GC seal item)",
            )

    # Priority 2: Crystal category — always MB
    if ingredient.category == CRYSTAL_CATEGORY:
        price_data = prices.get(item_id)
        ppu = price_data.avg_sale_price if price_data else 0
        return IngredientCost(
            item_id=item_id, name=name, amount=amount,
            price_per_unit=ppu, total_cost=ppu * amount, source="crystal",
        )

    # Priority 3: NPC vendor price (but not GC seal items which have misleading prices)
    if ingredient.npc_price > 0 and item_id not in GC_SEAL_ITEMS:
        return IngredientCost(
            item_id=item_id, name=name, amount=amount,
            price_per_unit=ingredient.npc_price,
            total_cost=ingredient.npc_price * amount,
            source="npc",
        )

    # Priority 4: Gathered heuristic
    price_data = prices.get(item_id)
    mb_price = price_data.avg_sale_price if price_data else 0
    if not ingredient.has_recipe and ingredient.npc_price == 0 and 0 < mb_price < GATHERED_THRESHOLD:
        return IngredientCost(
            item_id=item_id, name=name, amount=amount,
            price_per_unit=0, total_cost=0, source="gathered",
        )

    # Priority 5: MB fallback
    ppu = mb_price if mb_price > 0 else 0
    cost = IngredientCost(
        item_id=item_id, name=name, amount=amount,
        price_per_unit=ppu, total_cost=ppu * amount, source="mb",
    )

    # Check 1-level recursive craft alternative
    if ingredient.has_recipe and item_id in garland_items:
        sub_item = garland_items[item_id]
        if sub_item.ingredients:
            sub_cost = 0
            for sub_ing in sub_item.ingredients:
                sub_resolved = resolve_ingredient_cost(
                    sub_ing, prices, {}, gc_seals_free=gc_seals_free,
                )
                sub_cost += sub_resolved.total_cost
            if sub_cost > 0 and ppu > 0:
                craft_ppu = sub_cost / sub_item.craft_yield
                if craft_ppu < ppu:
                    cost.craft_alternative = craft_ppu
                    cost.craft_savings_pct = ((ppu - craft_ppu) / ppu) * 100

    return cost


def calculate_margin(
    item: GarlandItem,
    prices: dict[int, PriceData],
    garland_items: dict[int, GarlandItem],
    gc_seals_free: bool = False,
    world_prices: dict[int, PriceData] | None = None,
) -> MarginResult | None:
    # Use world-specific prices for revenue if available, DC-wide for ingredients
    if world_prices and item.item_id in world_prices:
        sell_data = world_prices[item.item_id]
    else:
        sell_data = prices.get(item.item_id)

    if not sell_data or sell_data.avg_sale_price <= 0:
        return None

    mb_price = sell_data.avg_sale_price
    revenue = mb_price * (1 - TAX_RATE)
    velocity = sell_data.nq_sale_velocity

    ingredient_costs = []
    craft_cost_total = 0
    for ing in item.ingredients:
        ing_cost = resolve_ingredient_cost(ing, prices, garland_items, gc_seals_free)
        ingredient_costs.append(ing_cost)
        craft_cost_total += ing_cost.total_cost

    if craft_cost_total <= 0:
        return None

    # Divide by yield — one craft may produce multiple units
    craft_cost = craft_cost_total / item.craft_yield
    margin = revenue - craft_cost
    margin_pct = (margin / craft_cost) * 100
    profit_per_day = margin * velocity

    return MarginResult(
        item_id=item.item_id,
        name=item.name,
        mb_price=mb_price,
        craft_cost=craft_cost,
        margin=margin,
        margin_pct=margin_pct,
        revenue=revenue,
        sale_velocity=velocity,
        profit_per_day=profit_per_day,
        is_stale=sell_data.is_stale,
        ingredient_costs=ingredient_costs,
    )
