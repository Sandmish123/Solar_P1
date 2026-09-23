import asyncio
import json

import httpx
import pytest

from app.models.building_cache import BuildingCache
from app.services import buildings
from app.services.buildings import ASSUMED_HEIGHT_M, cache_key, get_buildings, parse_buildings

# Bound at import, before the autouse offline fixture swaps the module attribute.
real_fetch_buildings = buildings.fetch_buildings


def _lookup(db, lat, lon):
    return asyncio.run(get_buildings(db, lat, lon))


def test_cache_key_is_a_fine_integer_grid():
    # ~11 m cells: which buildings shade you changes street by street.
    assert cache_key(28.507563, 77.061796, 150) == (285076, 770618, 150)
    assert all(isinstance(part, int) for part in cache_key(28.5, 77.1, 150))


def test_parse_real_overpass_response(overpass_payload):
    parsed = parse_buildings(overpass_payload)

    assert len(parsed) > 10
    first = parsed[0]
    assert len(first["polygon"]) >= 3
    assert first["height_m"] > 0
    assert {b["height_source"] for b in parsed} <= {"tag", "levels", "assumed"}


@pytest.mark.parametrize("tags, expected_height, expected_source", [
    ({"height": "12"}, 12.0, "tag"),
    ({"height": "12.5 m"}, 12.5, "tag"),
    ({"building:levels": "3"}, 9.0, "levels"),
    ({"height": "not-a-number", "building:levels": "2"}, 6.0, "levels"),
    ({}, ASSUMED_HEIGHT_M, "assumed"),
])
def test_height_parsing(tags, expected_height, expected_source):
    payload = {"elements": [{"geometry": [{"lat": 1, "lon": 1}] * 4, "tags": tags}]}
    building = parse_buildings(payload)[0]
    assert building["height_m"] == expected_height
    assert building["height_source"] == expected_source


def test_parse_skips_geometry_that_is_not_a_ring():
    payload = {"elements": [{"geometry": [{"lat": 1, "lon": 1}] * 2, "tags": {}}]}
    assert parse_buildings(payload) == []


def test_parse_rejects_a_non_overpass_body():
    with pytest.raises(ValueError):
        parse_buildings({"nope": True})


def test_second_lookup_hits_the_cache(db, offline_overpass):
    first = _lookup(db, 26.9124, 75.7873)
    second = _lookup(db, 26.9124, 75.7873)

    assert len(offline_overpass) == 1
    assert second == first


def test_lookup_queries_the_cell_centre(db, offline_overpass):
    _lookup(db, 19.076123, 72.877656)
    assert offline_overpass == [(19.0761, 72.8777, 150)]


@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
def test_outage_returns_none_and_is_not_cached(db, monkeypatch, error):
    async def failing_fetch(*args):
        raise error

    monkeypatch.setattr(buildings, "fetch_buildings", failing_fetch)
    # None means "geometry unknown"; the caller must not invent a skyline.
    assert _lookup(db, 22.5726, 88.3639) is None
    assert db.query(BuildingCache).filter_by(lat_key=225726, lon_key=883639).count() == 0


def test_malformed_response_returns_none(db, monkeypatch):
    async def junk_fetch(*args):
        return {"unexpected": True}

    monkeypatch.setattr(buildings, "fetch_buildings", junk_fetch)
    assert _lookup(db, 13.0827, 80.2707) is None


def test_fetch_posts_an_overpass_query(monkeypatch, overpass_payload):
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        seen["url"] = str(request.url)
        return httpx.Response(200, json=overpass_payload)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))

    payload = asyncio.run(real_fetch_buildings(28.5076, 77.0618, 150))

    assert payload == overpass_payload
    assert 'way(around:150,28.5076,77.0618)["building"]' in seen["body"]
    assert "out geom" in seen["body"]


def test_fetch_raises_on_server_error(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(
                            lambda request: httpx.Response(504, text="gateway timeout")), **kw))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(real_fetch_buildings(28.5076, 77.0618, 150))


def test_fetch_retries_once_before_giving_up(monkeypatch, overpass_payload):
    """Overpass 504s under load often enough that one attempt usually fails."""
    monkeypatch.setattr(buildings, "OVERPASS_RETRY_DELAY_S", 0)
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(200, json=overpass_payload) if len(attempts) > 1 else httpx.Response(504, text="busy")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))

    assert asyncio.run(real_fetch_buildings(28.5076, 77.0618, 150)) == overpass_payload
    assert len(attempts) == 2


def test_fetch_gives_up_after_the_retry(monkeypatch):
    monkeypatch.setattr(buildings, "OVERPASS_RETRY_DELAY_S", 0)
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(504, text="busy")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(real_fetch_buildings(28.5076, 77.0618, 150))
    assert len(attempts) == buildings.OVERPASS_ATTEMPTS
