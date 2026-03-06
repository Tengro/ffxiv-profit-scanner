import statistics
import sys
import threading
import time
from dataclasses import dataclass, field

import requests

from scanner import cache

BASE_URL = "https://universalis.app/api/v2"
MAX_BATCH_SIZE = 100
OUTLIER_FACTOR = 3.0  # Sales more than 3x away from median are outliers
MAX_RETRIES = 3

_last_request_time = 0.0
_rate_lock = threading.Lock()
RATE_LIMIT_MS = 250  # 250ms between requests — gentle on Universalis


def _rate_limit():
    global _last_request_time
    with _rate_lock:
        elapsed = time.time() - _last_request_time
        if elapsed < RATE_LIMIT_MS / 1000:
            time.sleep(RATE_LIMIT_MS / 1000 - elapsed)
        _last_request_time = time.time()


def _request_with_retry(url: str, params: dict = None) -> requests.Response:
    """GET with exponential backoff for 429/5xx errors."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=30)
        except requests.exceptions.Timeout:
            wait = 2 ** (attempt + 1)
            print(f"  Universalis timeout, retrying in {wait}s ({attempt + 1}/{MAX_RETRIES})",
                  file=sys.stderr)
            time.sleep(wait)
            continue

        if resp.status_code == 200:
            return resp
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
        elif resp.status_code >= 500:
            wait = 2 ** (attempt + 1)
        else:
            resp.raise_for_status()
        print(f"  Universalis HTTP {resp.status_code}, retrying in {wait}s ({attempt + 1}/{MAX_RETRIES})",
              file=sys.stderr)
        time.sleep(wait)

    # Final attempt — let it raise
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp


@dataclass
class WorldListing:
    world_name: str
    price_per_unit: int
    quantity: int
    is_hq: bool


@dataclass
class PriceData:
    item_id: int
    avg_sale_price: float
    min_price: int
    current_avg_price: float
    nq_sale_velocity: float
    last_upload_time: int
    is_stale: bool
    listings: list[WorldListing] = field(default_factory=list)
    recent_sales: list[dict] = field(default_factory=list)


def _robust_average(prices: list[int | float]) -> float:
    """Compute outlier-resistant average price.

    Uses median as anchor, filters out anything more than OUTLIER_FACTOR
    away from the median, then averages survivors.
    """
    valid = [p for p in prices if p > 0]
    if not valid:
        return 0
    if len(valid) == 1:
        return valid[0]

    med = statistics.median(valid)
    if med <= 0:
        return 0

    lower = med / OUTLIER_FACTOR
    upper = med * OUTLIER_FACTOR
    filtered = [p for p in valid if lower <= p <= upper]

    if not filtered:
        return med
    return statistics.mean(filtered)


def _parse_item_data(item_id: int, data: dict) -> PriceData:
    now = time.time()
    last_upload = data.get("lastUploadTime", 0)
    # lastUploadTime is in milliseconds
    if last_upload > 1e12:
        last_upload_sec = last_upload / 1000
    else:
        last_upload_sec = last_upload
    is_stale = (now - last_upload_sec) > 86400  # 24 hours

    listings = []
    for listing in data.get("listings", []):
        listings.append(WorldListing(
            world_name=listing.get("worldName", ""),
            price_per_unit=listing.get("pricePerUnit", 0),
            quantity=listing.get("quantity", 0),
            is_hq=listing.get("hq", False),
        ))

    recent_sales = []
    for sale in data.get("recentHistory", []):
        recent_sales.append({
            "price": sale.get("pricePerUnit", 0),
            "quantity": sale.get("quantity", 0),
            "timestamp": sale.get("timestamp", 0),
            "world_name": sale.get("worldName", ""),
            "hq": sale.get("hq", False),
        })

    # Compute robust average from recent sales (outlier-resistant)
    robust_avg = _robust_average([s["price"] for s in recent_sales])
    # Fall back to API average if we don't have enough sales data
    avg_price = robust_avg if robust_avg > 0 else data.get("averagePrice", 0)

    return PriceData(
        item_id=item_id,
        avg_sale_price=avg_price,
        min_price=data.get("minPrice", 0),
        current_avg_price=data.get("currentAveragePrice", 0),
        nq_sale_velocity=data.get("nqSaleVelocity", data.get("regularSaleVelocity", 0)),
        last_upload_time=last_upload,
        is_stale=is_stale,
        listings=listings,
        recent_sales=recent_sales,
    )


def fetch_prices(
    item_ids: list[int],
    dc: str,
    no_cache: bool = False,
    allow_stale: bool = False,
    listings: int = 10,
    entries: int = 30,
) -> dict[int, PriceData]:
    results = {}
    to_fetch = []

    # Check cache first
    if not no_cache:
        for item_id in item_ids:
            cached = cache.get("universalis", f"{dc}_{item_id}", allow_stale=allow_stale)
            if cached:
                results[item_id] = _parse_item_data(item_id, cached)
            else:
                to_fetch.append(item_id)
    else:
        to_fetch = list(item_ids)

    # Batch fetch remaining
    for i in range(0, len(to_fetch), MAX_BATCH_SIZE):
        batch = to_fetch[i:i + MAX_BATCH_SIZE]
        _rate_limit()

        ids_str = ",".join(str(x) for x in batch)
        url = f"{BASE_URL}/{dc}/{ids_str}"
        resp = _request_with_retry(url, params={"listings": listings, "entries": entries})
        data = resp.json()

        if len(batch) == 1:
            # Single item: response is the item data directly
            item_id = batch[0]
            if not no_cache:
                cache.put("universalis", f"{dc}_{item_id}", data)
            results[item_id] = _parse_item_data(item_id, data)
        else:
            # Batch: response wraps in {"items": {"id": {...}}}
            items = data.get("items", {})
            for str_id, item_data in items.items():
                item_id = int(str_id)
                if not no_cache:
                    cache.put("universalis", f"{dc}_{item_id}", item_data)
                results[item_id] = _parse_item_data(item_id, item_data)

    return results


def fetch_prices_lightweight(
    item_ids: list[int],
    dc: str,
    no_cache: bool = False,
    allow_stale: bool = False,
    on_batch: callable = None,
) -> dict[int, dict]:
    """Fetch just averagePrice + velocity for items. Cached per-item under lite_ prefix."""
    result = {}
    to_fetch = []

    if not no_cache:
        for item_id in item_ids:
            cached = cache.get("universalis", f"lite_{dc}_{item_id}", allow_stale=allow_stale)
            if cached is not None:
                result[item_id] = cached
            else:
                to_fetch.append(item_id)
    else:
        to_fetch = list(item_ids)

    if not to_fetch:
        if on_batch:
            on_batch(1, 1)
        return result

    total_batches = (len(to_fetch) + 99) // 100
    for i in range(0, len(to_fetch), MAX_BATCH_SIZE):
        batch = to_fetch[i:i + MAX_BATCH_SIZE]
        batch_num = i // MAX_BATCH_SIZE + 1
        ids_str = ",".join(str(x) for x in batch)
        try:
            resp = _request_with_retry(
                f"{BASE_URL}/{dc}/{ids_str}",
                params={"listings": 0, "entries": 1},
            )
            data = resp.json()
            if len(batch) == 1:
                result[batch[0]] = data
                if not no_cache:
                    cache.put("universalis", f"lite_{dc}_{batch[0]}", data)
            else:
                for k, v in data.get("items", {}).items():
                    item_id = int(k)
                    result[item_id] = v
                    if not no_cache:
                        cache.put("universalis", f"lite_{dc}_{item_id}", v)
        except requests.exceptions.Timeout:
            print(f"  Warning: Batch {batch_num}/{total_batches} timed out after retries",
                  file=sys.stderr)
        except requests.exceptions.HTTPError as e:
            print(f"  Warning: Batch {batch_num}/{total_batches} HTTP {e.response.status_code} after retries",
                  file=sys.stderr)
        except Exception as e:
            print(f"  Warning: Batch {batch_num}/{total_batches} failed: {e}",
                  file=sys.stderr)
        if on_batch and batch_num % 5 == 0:
            on_batch(batch_num, total_batches)
        time.sleep(RATE_LIMIT_MS / 1000)

    return result
