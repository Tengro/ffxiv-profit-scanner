import json
import os
import time
from pathlib import Path


CACHE_DIR = Path.home() / ".ffxiv-scanner"

# TTL in seconds; None = infinite
NAMESPACE_TTL = {
    "garland": None,
    "universalis": 3600,  # 1 hour
}


def _cache_path(namespace: str, key: str) -> Path:
    return CACHE_DIR / namespace / f"{key}.json"


def get(namespace: str, key: str) -> dict | None:
    path = _cache_path(namespace, key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    ttl = NAMESPACE_TTL.get(namespace)
    if ttl is not None:
        cached_at = data.get("_cached_at", 0)
        if time.time() - cached_at > ttl:
            return None
    return data.get("payload")


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
