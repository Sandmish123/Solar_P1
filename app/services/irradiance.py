"""In-plane irradiation for a site, from PVGIS with a DB cache and a static fallback.

Failure behaviour:
- PVGIS 400 (bad coordinates, e.g. over the sea) -> InvalidLocationError. The operator
  mistyped the site; estimating irradiance for it would be silently wrong.
- Timeout, network error, 5xx, 429, malformed body -> fallback profile, source "fallback".
  The service being down must not block a proposal, but the result is marked.
"""
import json
import logging

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.irradiance_cache import IrradianceCache

logger = logging.getLogger(__name__)

PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc"
# Measured p50 ~0.8s. 10s is generous headroom without letting a hung upstream
# hold the request open.
PVGIS_TIMEOUT_S = 10.0

# PVGIS v5_3 H(i)_y for the reference Gurugram cell (28.51N 77.06E, 25 deg, south),
# so a fallback project calibrates back to the reference 1401 kWh/kWp.
FALLBACK_H_ANNUAL = 2149.08
# The original static India ~28N monthly shape, Jan..Dec.
_FALLBACK_SHAPE = [0.075, 0.080, 0.095, 0.100, 0.105, 0.085, 0.070, 0.070, 0.075, 0.085, 0.080, 0.080]


class InvalidLocationError(Exception):
    """PVGIS rejected the coordinates."""


def cache_key(latitude: float, longitude: float, tilt: float, azimuth: float) -> tuple:
    # 0.01 deg is ~1.1 km; irradiance is effectively constant across a cell.
    return round(latitude * 100), round(longitude * 100), round(tilt), round(azimuth)


def fallback_irradiance() -> dict:
    total = sum(_FALLBACK_SHAPE)
    return {
        "monthly_h": [FALLBACK_H_ANNUAL * f / total for f in _FALLBACK_SHAPE],
        "h_annual": FALLBACK_H_ANNUAL,
        "source": "fallback",
        "radiation_db": None,
    }


def parse_pvgis(payload: dict) -> dict:
    """Extract in-plane irradiation from a PVcalc response. Raises ValueError if malformed."""
    try:
        months = sorted(payload["outputs"]["monthly"]["fixed"], key=lambda m: m["month"])
        monthly_h = [float(m["H(i)_m"]) for m in months]
        h_annual = float(payload["outputs"]["totals"]["fixed"]["H(i)_y"])
        radiation_db = str(payload["inputs"]["meteo_data"]["radiation_db"])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unexpected PVGIS response shape: {exc!r}") from exc

    if len(monthly_h) != 12 or h_annual <= 0 or min(monthly_h) < 0:
        raise ValueError(f"implausible PVGIS values: {len(monthly_h)} months, H(i)_y={h_annual}")

    return {"monthly_h": monthly_h, "h_annual": h_annual, "source": "pvgis", "radiation_db": radiation_db}


async def fetch_pvgis(latitude: float, longitude: float, tilt: float, azimuth: float) -> dict:
    params = {
        "lat": latitude,
        "lon": longitude,
        "angle": tilt,
        "aspect": azimuth,
        # Only irradiation is read. Our own loss stack supplies the losses, so PVGIS
        # must not apply them as well.
        "peakpower": 1,
        "loss": 0,
        "outputformat": "json",
    }
    async with httpx.AsyncClient(timeout=PVGIS_TIMEOUT_S) as client:
        response = await client.get(PVGIS_URL, params=params)

    if response.status_code == 400:
        # e.g. {"message": "Location over the sea. Please, select another location", "status": 400}
        try:
            message = response.json().get("message", response.text)
        except ValueError:
            message = response.text
        raise InvalidLocationError(message)

    response.raise_for_status()
    return response.json()


async def get_irradiance(db: Session, latitude: float, longitude: float, tilt: float, azimuth: float) -> dict:
    """Irradiance for a site: cache, then PVGIS, then the static fallback.

    Commits the session when it writes a cache row, so call it before modifying
    any other objects in the same session.
    """
    lat_key, lon_key, tilt_key, azimuth_key = cache_key(latitude, longitude, tilt, azimuth)

    cached = (
        db.query(IrradianceCache)
        .filter_by(lat_key=lat_key, lon_key=lon_key, tilt_key=tilt_key, azimuth_key=azimuth_key)
        .first()
    )
    if cached:
        return {
            "monthly_h": json.loads(cached.monthly_h_json),
            "h_annual": cached.h_annual,
            "source": "pvgis",
            "radiation_db": cached.radiation_db,
        }

    # Query at the cell's own coordinates rather than the project's, so a cached
    # value never depends on which project in the cell happened to fetch it first.
    try:
        irradiance = parse_pvgis(await fetch_pvgis(lat_key / 100, lon_key / 100, tilt_key, azimuth_key))
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "PVGIS unavailable for cell (%s, %s) tilt=%s azimuth=%s, using fallback: %r",
            lat_key / 100, lon_key / 100, tilt_key, azimuth_key, exc,
        )
        return fallback_irradiance()

    db.add(IrradianceCache(
        lat_key=lat_key,
        lon_key=lon_key,
        tilt_key=tilt_key,
        azimuth_key=azimuth_key,
        monthly_h_json=json.dumps(irradiance["monthly_h"]),
        h_annual=irradiance["h_annual"],
        radiation_db=irradiance["radiation_db"],
    ))
    try:
        db.commit()
    except IntegrityError:
        # A concurrent calculation cached this cell first. Same query, same data.
        db.rollback()
    return irradiance
