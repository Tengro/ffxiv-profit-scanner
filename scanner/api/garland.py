import time
from dataclasses import dataclass, field

import requests

from scanner import cache

BASE_URL = "https://garlandtools.org"
ITEM_URL = f"{BASE_URL}/db/doc/item/en/3/{{item_id}}.json"
SEARCH_URL = f"{BASE_URL}/api/search.php"

_last_request_time = 0.0
RATE_LIMIT_MS = 200


def _rate_limit():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < RATE_LIMIT_MS / 1000:
        time.sleep(RATE_LIMIT_MS / 1000 - elapsed)
    _last_request_time = time.time()


@dataclass
class Ingredient:
    item_id: int
    amount: int
    name: str = ""
    npc_price: int = 0
    category: int = 0
    has_recipe: bool = False


@dataclass
class GatheringNode:
    node_id: int
    name: str
    level: int
    job: str         # "MIN", "BTN", "FSH"
    is_timed: bool   # Unspoiled or Ephemeral
    zone_id: int = 0


# Node type -> job mapping
_NODE_TYPE_JOB = {0: "MIN", 1: "MIN", 2: "BTN", 3: "BTN"}


@dataclass
class GarlandItem:
    item_id: int
    name: str
    category: int
    npc_price: int
    is_craftable: bool
    is_fc_workshop: bool
    craft_job: int
    ingredients: list[Ingredient] = field(default_factory=list)
    ingredient_items: dict[int, dict] = field(default_factory=dict)
    gathering_nodes: list[GatheringNode] = field(default_factory=list)
    is_gathered: bool = False


def _parse_item(data: dict, no_cache: bool = False) -> GarlandItem:
    item = data["item"]
    craft_list = item.get("craft", [])

    is_craftable = len(craft_list) > 0
    is_fc_workshop = False
    craft_job = 0
    ingredients = []

    if is_craftable:
        craft = craft_list[0]
        craft_job = craft.get("job", 0)
        is_fc_workshop = craft.get("fc", 0) == 1 and craft_job == 0

        # For FC workshop items, all phases are in a single craft entry's ingredients
        # with a "phase" field. Aggregate same-ID ingredients across phases.
        # For normal crafts, just use the first craft entry's ingredients.
        craft_entries = craft_list if is_fc_workshop else [craft]
        for c in craft_entries:
            for ing in c.get("ingredients", []):
                existing = next((i for i in ingredients if i.item_id == ing["id"]), None)
                if existing:
                    existing.amount += ing["amount"]
                else:
                    ingredients.append(Ingredient(
                        item_id=ing["id"],
                        amount=ing["amount"],
                    ))

    # Build ingredient_items from top-level ingredients array
    # Each entry IS the item data directly (has id, name, price, etc. at top level)
    ingredient_items = {}
    for ing_data in data.get("ingredients", []):
        ing_id = ing_data.get("id")
        if ing_id is not None:
            ingredient_items[ing_id] = ing_data
            # Also cache this ingredient individually
            if not no_cache:
                cache.put("garland", str(ing_id), {"item": ing_data})

    # Enrich ingredient entries with data from ingredient_items
    for ing in ingredients:
        ing_data = ingredient_items.get(ing.item_id, {})
        ing.name = ing_data.get("name", "")
        ing.npc_price = ing_data.get("price", 0)
        ing.category = ing_data.get("category", 0)
        ing.has_recipe = len(ing_data.get("craft", [])) > 0

    # Parse gathering nodes
    gathering_nodes = []
    node_ids = set(item.get("nodes", []))
    fishing_spot_ids = set(item.get("fishingSpots", []))

    for partial in data.get("partials", []):
        obj = partial.get("obj", {})
        p_type = partial.get("type")
        # Partial IDs can be strings or ints — normalize to int
        raw_id = partial.get("id", obj.get("i"))
        try:
            p_id = int(raw_id) if raw_id is not None else None
        except (ValueError, TypeError):
            p_id = None

        if p_type == "node" and p_id in node_ids:
            node_type = obj.get("t", -1)
            job = _NODE_TYPE_JOB.get(node_type, "MIN")
            lt = obj.get("lt", "")
            gathering_nodes.append(GatheringNode(
                node_id=p_id,
                name=obj.get("n", ""),
                level=obj.get("l", 0),
                job=job,
                is_timed=lt in ("Unspoiled", "Ephemeral"),
                zone_id=obj.get("z", 0),
            ))
        elif p_type == "fishing" and p_id in fishing_spot_ids:
            gathering_nodes.append(GatheringNode(
                node_id=p_id,
                name=obj.get("n", ""),
                level=obj.get("l", 0),
                job="FSH",
                is_timed=False,
                zone_id=obj.get("z", 0),
            ))

    is_gathered = len(gathering_nodes) > 0

    return GarlandItem(
        item_id=item["id"],
        name=item.get("name", ""),
        category=item.get("category", 0),
        npc_price=item.get("price", 0),
        is_craftable=is_craftable,
        is_fc_workshop=is_fc_workshop,
        craft_job=craft_job,
        ingredients=ingredients,
        ingredient_items=ingredient_items,
        gathering_nodes=gathering_nodes,
        is_gathered=is_gathered,
    )


def fetch_item(item_id: int, no_cache: bool = False) -> GarlandItem:
    if not no_cache:
        # Try full cached response first (has top-level ingredients array)
        cached = cache.get("garland", f"full_{item_id}")
        if cached and "ingredients" in cached:
            return _parse_item(cached, no_cache=True)

    _rate_limit()
    url = ITEM_URL.format(item_id=item_id)
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if not no_cache:
        cache.put("garland", f"full_{item_id}", data)

    return _parse_item(data, no_cache=no_cache)


def search_items(query: str) -> list[dict]:
    _rate_limit()
    resp = requests.get(
        SEARCH_URL,
        params={"text": query, "type": "item", "lang": "en"},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json()
    return [{"id": r["id"], "name": r.get("obj", {}).get("n", "")} for r in results]
