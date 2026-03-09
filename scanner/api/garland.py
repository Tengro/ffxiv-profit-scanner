import threading
import time
from dataclasses import dataclass, field

import requests

from scanner import cache

BASE_URL = "https://garlandtools.org"
ITEM_URL = f"{BASE_URL}/db/doc/item/en/3/{{item_id}}.json"
NODE_BROWSE_URL = f"{BASE_URL}/db/doc/browse/en/2/node.json"
FISHING_BROWSE_URL = f"{BASE_URL}/db/doc/browse/en/2/fishing.json"
NODE_URL = f"{BASE_URL}/db/doc/node/en/2/{{node_id}}.json"
FISHING_URL = f"{BASE_URL}/db/doc/fishing/en/2/{{spot_id}}.json"
SEARCH_URL = f"{BASE_URL}/api/search.php"

_last_request_time = 0.0
_rate_lock = threading.Lock()
RATE_LIMIT_MS = 200


def _rate_limit():
    global _last_request_time
    with _rate_lock:
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
    craft_yield: int = 1
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
    craft_yield = 1
    ingredients = []

    if is_craftable:
        craft = craft_list[0]
        craft_job = craft.get("job", 0)
        craft_yield = craft.get("yield", 1)
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
        craft_yield=craft_yield,
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


def fetch_gathering_items(
    job_levels: dict[str, int],
    no_cache: bool = False,
    on_progress: callable = None,
) -> list[dict]:
    """Get all gatherable item IDs filtered by job type and level.

    Uses the node/fishing browse endpoints to find matching nodes,
    then fetches each node to get its item IDs.

    job_levels: e.g. {"MIN": 80, "BTN": 60}
    Returns list of dicts: {item_id, name, job, level, location, is_timed}
    """
    def _prog(msg):
        if on_progress:
            on_progress(msg)

    # Fetch node browse (cached permanently under garland namespace)
    _prog("Fetching gathering node index...")
    node_browse = _fetch_browse("node_browse", NODE_BROWSE_URL, no_cache)
    fishing_browse = _fetch_browse("fishing_browse", FISHING_BROWSE_URL, no_cache)

    # Filter nodes by job type and level
    matching_nodes = []  # (node_id, job, level, name, is_timed, source_type)
    for node in node_browse:
        node_type = node.get("t", -1)
        job = _NODE_TYPE_JOB.get(node_type)
        if not job or job not in job_levels:
            continue
        level = node.get("l", 0)
        if level > job_levels[job]:
            continue
        lt = node.get("lt", "")
        matching_nodes.append((
            node["i"], job, level, node.get("n", ""),
            lt in ("Unspoiled", "Ephemeral", "Legendary", "Concealed"),
            "node",
        ))

    if "FSH" in job_levels:
        for spot in fishing_browse:
            level = spot.get("l", 0)
            if level > job_levels["FSH"]:
                continue
            matching_nodes.append((
                spot["i"], "FSH", level, spot.get("n", ""),
                False, "fishing",
            ))

    _prog(f"Found {len(matching_nodes)} matching nodes, fetching items...")

    # Fetch each matching node to get item IDs
    # item_id -> best (lowest level) node info
    items: dict[int, dict] = {}
    for i, (node_id, job, level, location, is_timed, source_type) in enumerate(matching_nodes):
        if (i + 1) % 20 == 0:
            _prog(f"Fetching node items... {i + 1}/{len(matching_nodes)}")

        node_items = _fetch_node_items(node_id, source_type, no_cache)
        for item_entry in node_items:
            item_id = item_entry["id"]
            item_level = item_entry.get("lvl") or level  # Fall back to node level
            name = item_entry.get("name", "")
            if not name:
                continue  # Skip unnamed/invalid items
            entry = {
                "item_id": item_id,
                "name": name,
                "job": job,
                "level": item_level,
                "location": location,
                "is_timed": is_timed,
            }
            # Keep the lowest-level node for each item
            if item_id not in items or item_level < items[item_id]["level"]:
                items[item_id] = entry

    _prog(f"Found {len(items)} unique gatherable items")
    return list(items.values())


def _fetch_browse(cache_key: str, url: str, no_cache: bool) -> list[dict]:
    """Fetch a Garland browse endpoint (cached permanently)."""
    if not no_cache:
        cached = cache.get("garland", cache_key)
        if cached:
            return cached

    _rate_limit()
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("browse", [])

    if not no_cache:
        cache.put("garland", cache_key, data)
    return data


def _fetch_node_items(node_id: int, source_type: str, no_cache: bool) -> list[dict]:
    """Fetch a single node/fishing-spot and return its items with names."""
    cache_key = f"{source_type}_{node_id}"
    if not no_cache:
        cached = cache.get("garland", cache_key)
        if cached is not None:
            return cached

    _rate_limit()
    if source_type == "fishing":
        url = FISHING_URL.format(spot_id=node_id)
    else:
        url = NODE_URL.format(node_id=node_id)

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        if not no_cache:
            cache.put("garland", cache_key, [])
        return []

    # Get item IDs and levels from the node/fishing data
    node_data = data.get(source_type, data.get("node", {}))
    raw_items = node_data.get("items", [])

    # Build name lookup from partials
    name_map = {}
    for partial in data.get("partials", []):
        if partial.get("type") == "item":
            obj = partial.get("obj", {})
            pid = obj.get("i", partial.get("id"))
            if pid is not None:
                name_map[int(pid)] = obj.get("n", "")

    result = []
    for item in raw_items:
        if isinstance(item, dict):
            item_id = item.get("id")
            lvl = item.get("lvl")  # None if not present (mining/botany nodes)
        else:
            item_id = item
            lvl = None
        if item_id is not None:
            result.append({
                "id": int(item_id),
                "lvl": lvl,
                "name": name_map.get(int(item_id), ""),
            })

    if not no_cache:
        cache.put("garland", cache_key, result)
    return result


def is_hunting_material(item_id: int, no_cache: bool = False) -> bool:
    """Check if an item is a hunting material (mob drop, tradeable).

    Hybrid heuristic: ventures + !nodes + !craft + tradeable + no GC seal shop.
    The 'drops' field only covers through Stormblood (patch 4.x), so we use
    'ventures' as the primary signal and exclude seal-only items via tradeShops.
    """
    cache_key = f"huntv2_{item_id}"
    if not no_cache:
        cached = cache.get("garland", cache_key)
        if cached is not None:
            return cached

    _rate_limit()
    url = ITEM_URL.format(item_id=item_id)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        if not no_cache:
            cache.put("garland", cache_key, False)
        return False

    item = data.get("item", {})
    has_ventures = "ventures" in item
    has_nodes = "nodes" in item or "fishingSpots" in item
    has_craft = len(item.get("craft", [])) > 0
    tradeable = item.get("tradeable", 0) == 1
    gc_seal_cost = _extract_gc_seal_cost(item)
    result = has_ventures and not has_nodes and not has_craft and tradeable and gc_seal_cost == 0

    if not no_cache:
        cache.put("garland", cache_key, result)
    return result


# GC seal currency IDs (Garland uses string IDs in tradeShops)
GC_SEAL_CURRENCY_IDS = {"20", "21", "22"}  # Storm, Serpent, Flame


def _extract_gc_seal_cost(item: dict) -> int:
    """Extract GC seal cost from item's tradeShops. Returns seal amount or 0."""
    for shop in item.get("tradeShops", []):
        for listing in shop.get("listings", []):
            for c in listing.get("currency", []):
                if str(c.get("id")) in GC_SEAL_CURRENCY_IDS:
                    return int(c.get("amount", 0))
    return 0


def fetch_item_name(item_id: int, no_cache: bool = False) -> str:
    """Get an item's name from Garland. Uses cache when available."""
    # Check if we already have full item data cached
    if not no_cache:
        cached = cache.get("garland", f"full_{item_id}")
        if cached:
            return cached.get("item", {}).get("name", "")

    _rate_limit()
    url = ITEM_URL.format(item_id=item_id)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return ""

    if not no_cache:
        cache.put("garland", f"full_{item_id}", data)

    return data.get("item", {}).get("name", "")


# FFXIV craft job ID -> abbreviation
CRAFT_JOB_MAP = {
    8: "CRP", 9: "BSM", 10: "ARM", 11: "GSM",
    12: "LTW", 13: "WVR", 14: "ALC", 15: "CUL",
}


def check_craftable_items(
    item_ids: list[int],
    job_levels: dict[str, int],
    no_cache: bool = False,
    on_progress: callable = None,
) -> dict[int, dict]:
    """Check which items are craftable within given job levels.

    job_levels: e.g. {"CUL": 90, "WVR": 80}
    Returns {item_id: {name, job, level}} for matches.
    """
    results = {}
    for i, item_id in enumerate(item_ids):
        if on_progress and (i + 1) % 50 == 0:
            on_progress(f"Checking recipes... {i + 1}/{len(item_ids)}")

        cache_key = f"craft_{item_id}"
        if not no_cache:
            cached = cache.get("garland", cache_key)
            if cached is not None:
                # cached is either False or {job, level, name}
                if cached and isinstance(cached, dict):
                    job_abbr = cached["job"]
                    recipe_lvl = cached["level"]
                    if job_abbr in job_levels and recipe_lvl <= job_levels[job_abbr]:
                        results[item_id] = cached
                continue

        _rate_limit()
        url = ITEM_URL.format(item_id=item_id)
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            if not no_cache:
                cache.put("garland", cache_key, False)
            continue

        item = data.get("item", {})
        craft_list = item.get("craft", [])
        if not craft_list:
            if not no_cache:
                cache.put("garland", cache_key, False)
            continue

        craft = craft_list[0]
        job_id = craft.get("job", 0)
        recipe_lvl = craft.get("lvl", 0)
        job_abbr = CRAFT_JOB_MAP.get(job_id)

        if not job_abbr:
            if not no_cache:
                cache.put("garland", cache_key, False)
            continue

        craft_info = {
            "name": item.get("name", ""),
            "job": job_abbr,
            "level": recipe_lvl,
        }
        if not no_cache:
            cache.put("garland", cache_key, craft_info)

        if job_abbr in job_levels and recipe_lvl <= job_levels[job_abbr]:
            results[item_id] = craft_info

    return results


def check_hunting_items(
    item_ids: list[int],
    no_cache: bool = False,
    on_progress: callable = None,
) -> dict[int, str]:
    """Check which items are hunting materials (mob drops).

    Hybrid heuristic: ventures + !nodes + !craft + tradeable + no GC seal shop.
    Covers all expansions (ARR through Dawntrail) while filtering out seal-only
    items like Petrified Log.

    Returns {item_id: name} for matches.
    """
    results = {}
    for i, item_id in enumerate(item_ids):
        if on_progress and (i + 1) % 50 == 0:
            on_progress(f"Checking items... {i + 1}/{len(item_ids)}")

        cache_key = f"huntv2_{item_id}"
        if not no_cache:
            cached = cache.get("garland", cache_key)
            if cached is not None:
                if cached:
                    name = fetch_item_name(item_id, no_cache=no_cache)
                    if name:
                        results[item_id] = name
                continue

        _rate_limit()
        url = ITEM_URL.format(item_id=item_id)
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            if not no_cache:
                cache.put("garland", cache_key, False)
            continue

        item = data.get("item", {})
        has_ventures = "ventures" in item
        has_nodes = "nodes" in item or "fishingSpots" in item
        has_craft = len(item.get("craft", [])) > 0
        tradeable = item.get("tradeable", 0) == 1
        gc_seal_cost = _extract_gc_seal_cost(item)
        is_hunter = has_ventures and not has_nodes and not has_craft and tradeable and gc_seal_cost == 0

        if not no_cache:
            cache.put("garland", cache_key, is_hunter)
            cache.put("garland", f"full_{item_id}", data)

        if is_hunter:
            name = item.get("name", "")
            if name:
                results[item_id] = name

    return results


def check_seal_items(
    item_ids: list[int],
    no_cache: bool = False,
    on_progress: callable = None,
) -> dict[int, dict]:
    """Check which items are purchasable with GC seals.

    Returns {item_id: {name, seal_cost}} for tradeable items with GC seal shops.
    """
    results = {}
    for i, item_id in enumerate(item_ids):
        if on_progress and (i + 1) % 50 == 0:
            on_progress(f"Checking items... {i + 1}/{len(item_ids)}")

        cache_key = f"seal_{item_id}"
        if not no_cache:
            cached = cache.get("garland", cache_key)
            if cached is not None:
                if cached and isinstance(cached, dict):
                    results[item_id] = cached
                continue

        _rate_limit()
        url = ITEM_URL.format(item_id=item_id)
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            if not no_cache:
                cache.put("garland", cache_key, False)
            continue

        item = data.get("item", {})
        tradeable = item.get("tradeable", 0) == 1
        seal_cost = _extract_gc_seal_cost(item)

        if tradeable and seal_cost > 0:
            seal_info = {
                "name": item.get("name", ""),
                "seal_cost": seal_cost,
            }
            if not no_cache:
                cache.put("garland", cache_key, seal_info)
                cache.put("garland", f"full_{item_id}", data)
            results[item_id] = seal_info
        else:
            if not no_cache:
                cache.put("garland", cache_key, False)

    return results


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
