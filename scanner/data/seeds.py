import json
from pathlib import Path

CRYSTAL_CATEGORY = 59
SEEDS_PATH = Path.home() / ".ffxiv-scanner" / "seeds.json"

# GC Seal items — these show misleading price values in Garland Tools
# seals = cost in GC seals to purchase
GC_SEAL_ITEMS = {
    5530: {"name": "Coke", "seals": 200},
    5261: {"name": "Aqueous Whetstone", "seals": 200},
    5339: {"name": "Potash", "seals": 200},
    5340: {"name": "Animal Fat", "seals": 200},
    5341: {"name": "Blackite", "seals": 200},
    5342: {"name": "Raziqsand", "seals": 200},
    7597: {"name": "Scheelite", "seals": 200},
    7598: {"name": "Petrified Log", "seals": 200},
    10335: {"name": "Borax", "seals": 250},
    12634: {"name": "Raziqcoat", "seals": 250},
}

# Hardcoded fallback — only used if seeds.json doesn't exist
_FALLBACK_WORKSHOP_IDS = [
    22527, 22528, 22529, 22530,  # Whale-class
    22531, 22532, 22533, 22534,  # Shark-class
    22535, 22536, 22537, 22538,  # Unkiu-class
    24348, 24349, 24350, 24351,  # Coelacanth-class
    24352, 24353, 24354, 24355,  # Syldra-class
]

_FALLBACK_VENDOR_ITEMS = {
    5093: {"name": "Steel Rivets", "price": 313},
    5058: {"name": "Steel Ingot", "price": 258},
    7013: {"name": "Spruce Lumber", "price": 168},
    5111: {"name": "Iron Rivets", "price": 22},
    5056: {"name": "Iron Ingot", "price": 18},
    5355: {"name": "Bomb Ash", "price": 172},
    12579: {"name": "Mythrite Ingot", "price": 2652},
    12585: {"name": "Titanium Ingot", "price": 2652},
    12599: {"name": "Holy Cedar Lumber", "price": 2496},
    12600: {"name": "Dark Chestnut Lumber", "price": 2496},
    5504: {"name": "Iron Nails", "price": 7},
}

# Cached loaded seeds
_loaded_seeds: dict | None = None


def _load_seeds() -> dict | None:
    global _loaded_seeds
    if _loaded_seeds is not None:
        return _loaded_seeds
    if SEEDS_PATH.exists():
        try:
            _loaded_seeds = json.loads(SEEDS_PATH.read_text())
            return _loaded_seeds
        except (json.JSONDecodeError, OSError):
            pass
    return None


def reload_seeds() -> None:
    """Force reload seeds from disk on next access."""
    global _loaded_seeds
    _loaded_seeds = None


def get_all_workshop_ids() -> list[int]:
    seeds = _load_seeds()
    if seeds and "workshop" in seeds:
        ids = []
        for subcategory in seeds["workshop"].values():
            for item in subcategory:
                ids.append(item["id"])
        return ids
    return list(_FALLBACK_WORKSHOP_IDS)


def get_workshop_ids_by_category(category: str | None = None) -> list[int]:
    if category is None:
        return get_all_workshop_ids()
    seeds = _load_seeds()
    if seeds and "workshop" in seeds:
        matching = []
        for subcat, items in seeds["workshop"].items():
            if category in subcat:
                matching.extend(item["id"] for item in items)
        return matching
    return get_all_workshop_ids()


def get_vendor_seed_ids() -> list[int]:
    seeds = _load_seeds()
    if seeds and "vendor" in seeds:
        return [item["id"] for item in seeds["vendor"]
                if item["id"] not in GC_SEAL_ITEMS]
    return [item_id for item_id in _FALLBACK_VENDOR_ITEMS
            if item_id not in GC_SEAL_ITEMS]


def get_vendor_items() -> dict[int, dict]:
    """Return vendor items as {id: {name, price}} dict."""
    seeds = _load_seeds()
    if seeds and "vendor" in seeds:
        return {
            item["id"]: {"name": item["name"], "price": item.get("npc_price", 0)}
            for item in seeds["vendor"]
            if item["id"] not in GC_SEAL_ITEMS
        }
    return {k: v for k, v in _FALLBACK_VENDOR_ITEMS.items()
            if k not in GC_SEAL_ITEMS}


def get_popular_craft_ids() -> list[int]:
    seeds = _load_seeds()
    if seeds and "popular_crafts" in seeds:
        return [item["id"] for item in seeds["popular_crafts"]]
    return []


def get_all_scan_ids() -> list[int]:
    """Return all scannable item IDs (workshop + popular crafts)."""
    ids = set(get_all_workshop_ids())
    ids.update(get_popular_craft_ids())
    return list(ids)
