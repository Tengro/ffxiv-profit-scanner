"""Smoke tests for API client functions — ensures they return correct types."""

from unittest.mock import patch, MagicMock

from scanner.api.universalis import fetch_prices, fetch_prices_lightweight, PriceData


def _mock_universalis_response(item_ids):
    """Build a fake Universalis multi-item response."""
    items = {}
    for item_id in item_ids:
        items[str(item_id)] = {
            "listings": [],
            "recentHistory": [
                {"pricePerUnit": 100, "quantity": 1, "timestamp": 0, "worldName": "Omega", "hq": False},
            ],
            "averagePrice": 100,
            "minPrice": 90,
            "currentAveragePrice": 100,
            "nqSaleVelocity": 2.0,
            "lastUploadTime": 0,
        }
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"items": items} if len(item_ids) > 1 else items.get(str(item_ids[0]), {})
    return resp


@patch("scanner.api.universalis._request_with_retry")
@patch("scanner.api.universalis.cache")
def test_fetch_prices_returns_dict(mock_cache, mock_request):
    mock_cache.get.return_value = None
    mock_request.return_value = _mock_universalis_response([101, 102])

    result = fetch_prices([101, 102], "Chaos", no_cache=True)
    assert isinstance(result, dict)
    assert len(result) == 2
    assert all(isinstance(v, PriceData) for v in result.values())


@patch("scanner.api.universalis._request_with_retry")
@patch("scanner.api.universalis.cache")
def test_fetch_prices_single_item(mock_cache, mock_request):
    mock_cache.get.return_value = None
    mock_request.return_value = _mock_universalis_response([101])

    result = fetch_prices([101], "Chaos", no_cache=True)
    assert isinstance(result, dict)
    assert 101 in result
    assert result[101].avg_sale_price == 100


@patch("scanner.api.universalis._request_with_retry")
@patch("scanner.api.universalis.cache")
def test_fetch_prices_lightweight_returns_dict(mock_cache, mock_request):
    mock_cache.get.return_value = None
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "items": {
            "101": {"averagePrice": 50, "nqSaleVelocity": 1.5},
            "102": {"averagePrice": 200, "nqSaleVelocity": 3.0},
        }
    }
    mock_request.return_value = resp

    result = fetch_prices_lightweight([101, 102], "Chaos", no_cache=True)
    assert isinstance(result, dict)
    assert len(result) == 2
