"""Tests for pricing logic — outlier filtering, ingredient costs, and margin calculation."""

import pytest

from scanner.api.universalis import _robust_average, PriceData
from scanner.api.garland import GarlandItem, Ingredient
from scanner.pricing import (
    resolve_ingredient_cost,
    calculate_margin,
    IngredientCost,
    MarginResult,
    TAX_RATE,
)
from scanner.data.seeds import GC_SEAL_ITEMS, CRYSTAL_CATEGORY


# ── _robust_average ─────────────────────────────────────────────


def test_robust_average_normal():
    assert _robust_average([100, 110, 105, 95, 100]) == pytest.approx(102, rel=0.01)


def test_robust_average_single():
    assert _robust_average([500]) == 500


def test_robust_average_empty():
    assert _robust_average([]) == 0


def test_robust_average_all_zeros():
    assert _robust_average([0, 0, 0]) == 0


def test_robust_average_filters_rmt_spike():
    # Typical RMT: one huge sale among normal ones
    prices = [100, 105, 95, 110, 100, 5_000_000]
    avg = _robust_average(prices)
    # Should be close to 102 (the normal prices), not pulled up by 5M
    assert avg < 200


def test_robust_average_filters_low_outlier():
    prices = [1000, 1050, 950, 1100, 1]
    avg = _robust_average(prices)
    assert avg > 900


def test_robust_average_all_outliers():
    # When all values are far from median, should return median
    prices = [1, 1000000]
    avg = _robust_average(prices)
    assert avg > 0


# ── resolve_ingredient_cost ──────────────────────────────────────


def _make_ingredient(item_id=100, amount=3, name="Test Item",
                     npc_price=0, category=0, has_recipe=False):
    return Ingredient(
        item_id=item_id, amount=amount, name=name,
        npc_price=npc_price, category=category, has_recipe=has_recipe,
    )


def _make_price_data(item_id=100, avg_price=500, velocity=2.0):
    return PriceData(
        item_id=item_id, avg_sale_price=avg_price, min_price=int(avg_price * 0.9),
        current_avg_price=avg_price, nq_sale_velocity=velocity,
        last_upload_time=0, is_stale=False,
    )


def test_npc_vendor_price():
    ing = _make_ingredient(npc_price=50)
    cost = resolve_ingredient_cost(ing, {}, {})
    assert cost.source == "npc"
    assert cost.price_per_unit == 50
    assert cost.total_cost == 150  # 50 * 3


def test_crystal_uses_mb():
    ing = _make_ingredient(category=CRYSTAL_CATEGORY)
    prices = {100: _make_price_data(avg_price=20)}
    cost = resolve_ingredient_cost(ing, prices, {})
    assert cost.source == "crystal"
    assert cost.price_per_unit == 20
    assert cost.total_cost == 60


def test_gc_seal_free():
    gc_id = list(GC_SEAL_ITEMS.keys())[0]
    ing = _make_ingredient(item_id=gc_id)
    cost = resolve_ingredient_cost(ing, {}, {}, gc_seals_free=True)
    assert cost.source == "gc_seals"
    assert cost.total_cost == 0


def test_gc_seal_not_free_uses_mb():
    gc_id = list(GC_SEAL_ITEMS.keys())[0]
    ing = _make_ingredient(item_id=gc_id)
    prices = {gc_id: _make_price_data(item_id=gc_id, avg_price=300)}
    cost = resolve_ingredient_cost(ing, prices, {}, gc_seals_free=False)
    assert "mb" in cost.source.lower()
    assert cost.price_per_unit == 300


def test_mb_fallback():
    ing = _make_ingredient()
    prices = {100: _make_price_data(avg_price=1000)}  # Above GATHERED_THRESHOLD
    cost = resolve_ingredient_cost(ing, prices, {})
    assert cost.source == "mb"
    assert cost.price_per_unit == 1000
    assert cost.total_cost == 3000


def test_gathered_heuristic():
    # No recipe, no NPC, cheap MB price → "gathered" (free)
    ing = _make_ingredient(npc_price=0, has_recipe=False)
    prices = {100: _make_price_data(avg_price=50)}
    cost = resolve_ingredient_cost(ing, prices, {})
    assert cost.source == "gathered"
    assert cost.total_cost == 0


def test_craft_alternative_detected():
    # Sub-item is craftable with cheaper ingredients
    sub_ing = _make_ingredient(item_id=200, amount=2, name="Sub Mat", npc_price=10)
    sub_item = GarlandItem(
        item_id=100, name="Test Item", category=0, npc_price=0,
        is_craftable=True, is_fc_workshop=False, craft_job=1, craft_yield=1,
        ingredients=[sub_ing],
    )
    ing = _make_ingredient(has_recipe=True)
    prices = {100: _make_price_data(avg_price=500)}
    garland_items = {100: sub_item}
    cost = resolve_ingredient_cost(ing, prices, garland_items)
    assert cost.craft_alternative is not None
    assert cost.craft_alternative < 500  # Craft cost (2 * 10 = 20) < MB (500)


def test_craft_alternative_with_yield():
    # Sub-item yields 3 per craft, so cost per unit = total / 3
    sub_ing = _make_ingredient(item_id=200, amount=2, name="Sub Mat", npc_price=100)
    sub_item = GarlandItem(
        item_id=100, name="Test Item", category=0, npc_price=0,
        is_craftable=True, is_fc_workshop=False, craft_job=1, craft_yield=3,
        ingredients=[sub_ing],
    )
    ing = _make_ingredient(has_recipe=True)
    prices = {100: _make_price_data(avg_price=500)}
    garland_items = {100: sub_item}
    cost = resolve_ingredient_cost(ing, prices, garland_items)
    # Craft cost: 2 * 100 = 200, yield 3 → 66.67 per unit
    assert cost.craft_alternative == pytest.approx(66.67, rel=0.01)


# ── calculate_margin ─────────────────────────────────────────────


def _make_garland_item(item_id=1, name="Finished Item", craft_yield=1, ingredients=None):
    if ingredients is None:
        ingredients = [_make_ingredient(npc_price=100)]
    return GarlandItem(
        item_id=item_id, name=name, category=0, npc_price=0,
        is_craftable=True, is_fc_workshop=False, craft_job=1,
        craft_yield=craft_yield, ingredients=ingredients,
    )


def test_basic_margin():
    item = _make_garland_item()
    prices = {1: _make_price_data(item_id=1, avg_price=1000, velocity=2.0)}
    result = calculate_margin(item, prices, {})
    assert result is not None
    assert result.mb_price == 1000
    assert result.craft_cost == 300  # 3 * 100
    assert result.revenue == 950  # 1000 * 0.95
    assert result.margin == 650  # 950 - 300
    assert result.profit_per_day == 1300  # 650 * 2.0


def test_margin_with_yield():
    item = _make_garland_item(craft_yield=3)
    prices = {1: _make_price_data(item_id=1, avg_price=200, velocity=5.0)}
    result = calculate_margin(item, prices, {})
    assert result is not None
    # Craft cost per unit: (3 * 100) / 3 = 100
    assert result.craft_cost == pytest.approx(100, rel=0.01)
    assert result.revenue == 190  # 200 * 0.95
    assert result.margin == pytest.approx(90, rel=0.01)


def test_margin_returns_none_no_price():
    item = _make_garland_item()
    result = calculate_margin(item, {}, {})
    assert result is None


def test_margin_returns_none_zero_cost():
    # All ingredients free (GC seals)
    gc_id = list(GC_SEAL_ITEMS.keys())[0]
    ing = _make_ingredient(item_id=gc_id, amount=1)
    item = _make_garland_item(ingredients=[ing])
    prices = {1: _make_price_data(item_id=1, avg_price=1000)}
    result = calculate_margin(item, prices, {}, gc_seals_free=True)
    assert result is None  # Zero craft cost → skip


def test_margin_with_world_prices():
    item = _make_garland_item()
    dc_prices = {1: _make_price_data(item_id=1, avg_price=800, velocity=1.0)}
    world_prices = {1: _make_price_data(item_id=1, avg_price=1200, velocity=3.0)}
    result = calculate_margin(item, dc_prices, {}, world_prices=world_prices)
    assert result.mb_price == 1200  # Uses world price
    assert result.sale_velocity == 3.0
