import asyncio
import copy

import httpx
import pytest

from app.models.irradiance_cache import IrradianceCache
from app.services import irradiance
from app.services.irradiance import (
    FALLBACK_H_ANNUAL,
    InvalidLocationError,
    cache_key,
    get_irradiance,
    parse_pvgis,
)

# Bound at import, before the autouse offline_pvgis fixture swaps the module attribute.
real_fetch_pvgis = irradiance.fetch_pvgis


def _lookup(db, lat, lon, tilt=25, azimuth=0):
    return asyncio.run(get_irradiance(db, lat, lon, tilt, azimuth))


def _mock_http(monkeypatch, handler):
    """Route the real fetch_pvgis through httpx.MockTransport."""
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )


# --- parsing ---------------------------------------------------------------

def test_parse_pvgis_fixture(pvgis_payload):
    parsed = parse_pvgis(pvgis_payload)

    assert len(parsed["monthly_h"]) == 12
    assert parsed["h_annual"] == pytest.approx(2149.08)
    assert sum(parsed["monthly_h"]) == pytest.approx(parsed["h_annual"], abs=0.1)
    assert parsed["source"] == "pvgis"
    assert parsed["radiation_db"] == "PVGIS-ERA5"


@pytest.mark.parametrize("mutate", [
    lambda p: p.pop("outputs"),
    lambda p: p["outputs"]["monthly"]["fixed"].pop(),
    lambda p: p["outputs"]["monthly"]["fixed"][0].update({"H(i)_m": -5}),
    lambda p: p["outputs"]["totals"]["fixed"].update({"H(i)_y": 0}),
])
def test_parse_rejects_malformed(pvgis_payload, mutate):
    payload = copy.deepcopy(pvgis_payload)
    mutate(payload)
    with pytest.raises(ValueError):
        parse_pvgis(payload)


def test_cache_key_uses_integers():
    # Position and orientation are integers so lookups never compare floats; mounting
    # is part of the key because it changes the temperature loss PVGIS reports.
    assert cache_key(28.507563, 77.061796, 25.4, -0.4) == (2851, 7706, 25, 0, "free")
    assert cache_key(28.507563, 77.061796, 25.4, -0.4, "building")[4] == "building"
    assert all(isinstance(k, int) for k in cache_key(28.5, 77.1, 25.0, 0.0)[:4])


def test_an_unknown_mounting_falls_back_to_free():
    assert cache_key(28.5, 77.1, 25, 0, "nonsense")[4] == "free"


# --- caching ---------------------------------------------------------------

def test_second_lookup_hits_cache(db, offline_pvgis):
    first = _lookup(db, 21.11, 79.08)
    second = _lookup(db, 21.11, 79.08)

    assert len(offline_pvgis) == 1
    assert second["source"] == "pvgis"
    assert second["monthly_h"] == first["monthly_h"]


def test_nearby_sites_share_a_cell_and_fetch_at_cell_centre(db, offline_pvgis):
    _lookup(db, 12.3401, 76.6399)
    _lookup(db, 12.3449, 76.6351)  # same 0.01 deg cell

    assert offline_pvgis == [(12.34, 76.64, 25, 0, "free")]


def test_orientation_is_part_of_the_key(db, offline_pvgis):
    _lookup(db, 22.57, 88.36, tilt=25, azimuth=0)
    _lookup(db, 22.57, 88.36, tilt=10, azimuth=0)
    _lookup(db, 22.57, 88.36, tilt=25, azimuth=-90)

    assert len(offline_pvgis) == 3


# --- failure behaviour -----------------------------------------------------

@pytest.mark.parametrize("error", [
    httpx.ConnectError("connection refused"),
    httpx.ReadTimeout("timed out"),
])
def test_outage_falls_back_and_is_not_cached(db, monkeypatch, error):
    async def failing_fetch(*args):
        raise error

    monkeypatch.setattr(irradiance, "fetch_pvgis", failing_fetch)
    result = _lookup(db, 17.38, 78.48)

    assert result["source"] == "fallback"
    assert result["h_annual"] == FALLBACK_H_ANNUAL
    # An outage must not poison the cache: the next calculation retries PVGIS.
    assert db.query(IrradianceCache).filter_by(lat_key=1738, lon_key=7848).count() == 0


def test_malformed_response_falls_back(db, monkeypatch):
    async def junk_fetch(*args):
        return {"outputs": {}}

    monkeypatch.setattr(irradiance, "fetch_pvgis", junk_fetch)
    assert _lookup(db, 26.91, 75.78)["source"] == "fallback"


def test_invalid_location_propagates(db, monkeypatch):
    async def rejecting_fetch(*args):
        raise InvalidLocationError("Location over the sea. Please, select another location")

    monkeypatch.setattr(irradiance, "fetch_pvgis", rejecting_fetch)
    with pytest.raises(InvalidLocationError, match="over the sea"):
        _lookup(db, 0.0, -30.0)


# --- the real HTTP client, against a mock transport -------------------------

def test_fetch_requests_irradiation_without_pvgis_losses(monkeypatch, pvgis_payload):
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json=pvgis_payload)

    _mock_http(monkeypatch, handler)
    payload = asyncio.run(real_fetch_pvgis(28.51, 77.06, 25, -90))

    assert payload == pvgis_payload
    # loss=0 or PVGIS double-counts losses our own stack already applies.
    assert seen["loss"] == "0"
    assert seen["peakpower"] == "1"
    assert (seen["lat"], seen["lon"], seen["angle"], seen["aspect"]) == ("28.51", "77.06", "25", "-90")


def test_fetch_400_is_invalid_location(monkeypatch):
    _mock_http(monkeypatch, lambda request: httpx.Response(
        400, json={"message": "Location over the sea. Please, select another location", "status": 400},
    ))
    with pytest.raises(InvalidLocationError, match="over the sea"):
        asyncio.run(real_fetch_pvgis(0.0, -30.0, 25, 0))


@pytest.mark.parametrize("status", [429, 500, 503])
def test_fetch_other_errors_raise_http_error(monkeypatch, status):
    # get_irradiance maps httpx.HTTPError to the fallback; 429 is load, not bad input.
    _mock_http(monkeypatch, lambda request: httpx.Response(status, text="busy"))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(real_fetch_pvgis(28.51, 77.06, 25, 0))


# --- P90 inputs and site temperature loss (Phase 7) -------------------------

def test_parse_extracts_variability_and_temperature_loss(pvgis_payload):
    parsed = parse_pvgis(pvgis_payload)

    assert parsed["e_annual"] == pytest.approx(1872.16, abs=0.5)
    assert parsed["sd_annual"] == pytest.approx(33.32, abs=0.5)
    # l_tg is reported negative; the loss stack stores magnitudes.
    assert parsed["temp_loss_pct"] == pytest.approx(10.98, abs=0.05)


def test_building_mounting_is_hotter_but_equally_sunny(pvgis_payload, pvgis_building_payload):
    free = parse_pvgis(pvgis_payload)
    building = parse_pvgis(pvgis_building_payload)

    # Mounting changes module temperature, not the sunlight falling on the plane.
    assert building["h_annual"] == pytest.approx(free["h_annual"], abs=0.1)
    assert building["temp_loss_pct"] > free["temp_loss_pct"]


def test_relative_sd_is_a_fraction_of_annual_yield(pvgis_payload):
    from app.services.irradiance import _with_relative_sd

    parsed = _with_relative_sd(parse_pvgis(pvgis_payload))
    assert parsed["relative_sd"] == pytest.approx(33.32 / 1872.16, rel=1e-3)


def test_fallback_admits_it_knows_no_variability_or_temperature():
    fallback = irradiance.fallback_irradiance()
    assert fallback["sd_annual"] is None
    assert fallback["temp_loss_pct"] is None
    assert fallback["relative_sd"] is None


def test_float_parsing_tolerates_pvgis_type_inconsistency():
    from app.services.irradiance import _as_float

    # PVGIS returns l_spec as a string while its siblings are numbers.
    assert _as_float("0.37") == 0.37
    assert _as_float(-10.98) == -10.98
    assert _as_float(None) is None
    assert _as_float("not a number") is None


def test_mounting_is_sent_to_pvgis_and_keyed_separately(db, offline_pvgis):
    _lookup(db, 23.25, 77.41)
    asyncio.run(get_irradiance(db, 23.25, 77.41, 25, 0, "building"))

    assert [call[4] for call in offline_pvgis] == ["free", "building"]
    # Two cache rows for one cell: the hotter roof needs its own temperature loss.
    assert asyncio.run(get_irradiance(db, 23.25, 77.41, 25, 0, "building"))["temp_loss_pct"] > \
           asyncio.run(get_irradiance(db, 23.25, 77.41, 25, 0, "free"))["temp_loss_pct"]
