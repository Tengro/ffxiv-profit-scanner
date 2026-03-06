import json
import os
import time
from pathlib import Path


CACHE_DIR = Path.home() / ".ffxiv-scanner"

# TTL in seconds; None = infinite
NAMESPACE_TTL = {
    "garland": None,
    "universalis": 10800,  # 3 hours
}


def _cache_path(namespace: str, key: str) -> Path:
    return CACHE_DIR / namespace / f"{key}.json"


def get(namespace: str, key: str, allow_stale: bool = False) -> dict | None:
    path = _cache_path(namespace, key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    ttl = NAMESPACE_TTL.get(namespace)
    if ttl is not None and not allow_stale:
        cached_at = data.get("_cached_at", 0)
        if time.time() - cached_at > ttl:
            return None
    return data.get("payload")


def namespace_age(namespace: str) -> float | None:
    """Return age in seconds of the most recent file in a namespace, or None if empty."""
    ns_dir = CACHE_DIR / namespace
    if not ns_dir.exists():
        return None
    newest = 0.0
    for f in ns_dir.iterdir():
        try:
            data = json.loads(f.read_text())
            cached_at = data.get("_cached_at", 0)
            if cached_at > newest:
                newest = cached_at
        except (json.JSONDecodeError, OSError):
            continue
    if newest == 0:
        return None
    return time.time() - newest


def put(namespace: str, key: str, payload: dict) -> None:
    path = _cache_path(namespace, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"_cached_at": time.time(), "payload": payload}
    path.write_text(json.dumps(data))


def clear(namespace: str | None = None) -> None:
    if namespace:
        ns_dir = CACHE_DIR / namespace
        if ns_dir.exists():
            for f in ns_dir.iterdir():
                f.unlink()
    else:
        import shutil
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)
