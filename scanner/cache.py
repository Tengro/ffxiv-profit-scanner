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
    """Return age in seconds of the most recent write in a namespace, or None if empty."""
    meta_path = CACHE_DIR / namespace / "_last_updated.json"
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text())
            return time.time() - data.get("_cached_at", 0)
        except (json.JSONDecodeError, OSError):
            pass
    # Fallback: check if namespace dir exists at all
    ns_dir = CACHE_DIR / namespace
    if not ns_dir.exists() or not any(ns_dir.iterdir()):
        return None
    # No metadata yet — scan once to bootstrap (will be fast next time)
    newest = 0.0
    for f in ns_dir.iterdir():
        if f.name == "_last_updated.json":
            continue
        try:
            data = json.loads(f.read_text())
            cached_at = data.get("_cached_at", 0)
            if cached_at > newest:
                newest = cached_at
        except (json.JSONDecodeError, OSError):
            continue
    if newest > 0:
        _write_namespace_meta(namespace, newest)
        return time.time() - newest
    return None


def _write_namespace_meta(namespace: str, cached_at: float) -> None:
    path = CACHE_DIR / namespace / "_last_updated.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"_cached_at": cached_at}))


def put(namespace: str, key: str, payload: dict) -> None:
    now = time.time()
    path = _cache_path(namespace, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"_cached_at": now, "payload": payload}
    path.write_text(json.dumps(data))
    _write_namespace_meta(namespace, now)


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
