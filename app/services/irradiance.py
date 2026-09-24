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
# PVGIS offers two mountings. Elevated rooftop racking with airflow behaves like
# "free"; flush-mounted or BIPV like "building", which runs hotter (-14.7% vs -11.0%
# at the reference site). The operator chooses, because picking one would be wrong for
# the other half of installs.
MOUNTINGS = ("free", "building")
DEFAULT_MOUNTING = "free"

FALLBACK_H_ANNUAL = 2149.08
# The original static India ~28N monthly shape, Jan..Dec.
_FALLBACK_SHAPE = [0.075, 0.080, 0.095, 0.100, 0.105, 0.085, 0.070, 0.070, 0.075, 0.085, 0.080, 0.080]


class InvalidLocationError(Exception):
    """PVGIS rejected the coordinates."""


def cache_key(latitude: float, longitude: float, tilt: float, azimuth: float,
              mounting: str = DEFAULT_MOUNTING) -> tuple:
    # 0.01 deg is ~1.1 km; irradiance is effectively constant across a cell.
    return (round(latitude * 100), round(longitude * 100), round(tilt), round(azimuth),
            mounting if mounting in MOUNTINGS else DEFAULT_MOUNTING)


def _as_float(value):
    """PVGIS is inconsistent about types - l_spec comes back as a string while its
    siblings are numbers - so never trust the JSON type."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _with_relative_sd(irradiance: dict) -> dict:
    """Interannual variability as a fraction, for P90. PVGIS gives SD against its own
    E_y, and the ratio carries over to our calibrated figure."""
    e_annual, sd_annual = irradiance.get("e_annual"), irradiance.get("sd_annual")
    irradiance["relative_sd"] = (
        sd_annual / e_annual if e_annual and sd_annual and e_annual > 0 else None
    )
    return irradiance


def fallback_irradiance() -> dict:
    total = sum(_FALLBACK_SHAPE)
    return {
        "monthly_h": [FALLBACK_H_ANNUAL * f / total for f in _FALLBACK_SHAPE],
        "h_annual": FALLBACK_H_ANNUAL,
        "source": "fallback",
        "radiation_db": None,
        # No dataset, so no variability and no site temperature: both stay unknown
        # rather than being guessed.
        "e_annual": None,
        "sd_annual": None,
        "relative_sd": None,
        "temp_loss_pct": None,
    }


def parse_pvgis(payload: dict) -> dict:
    """Extract in-plane irradiation from a PVcalc response. Raises ValueError if malformed."""
    try:
        months = sorted(payload["outputs"]["monthly"]["fixed"], key=lambda m: m["month"])
        monthly_h = [float(m["H(i)_m"]) for m in months]
        totals = payload["outputs"]["totals"]["fixed"]
        h_annual = float(totals["H(i)_y"])
        radiation_db = str(payload["inputs"]["meteo_data"]["radiation_db"])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unexpected PVGIS response shape: {exc!r}") from exc

    if len(monthly_h) != 12 or h_annual <= 0 or min(monthly_h) < 0:
        raise ValueError(f"implausible PVGIS values: {len(monthly_h)} months, H(i)_y={h_annual}")

    # Optional extras: absent in an older cached payload, so never fatal.
    e_annual = _as_float(totals.get("E_y"))
    sd_annual = _as_float(totals.get("SD_y"))
    # l_tg is reported negative (a loss); the loss stack stores magnitudes.
    temperature_loss = _as_float(totals.get("l_tg"))
    temp_loss_pct = abs(temperature_loss) if temperature_loss is not None else None

    return {
        "monthly_h": monthly_h,
        "h_annual": h_annual,
        "source": "pvgis",
        "radiation_db": radiation_db,
        "e_annual": e_annual,
        "sd_annual": sd_annual,
        "temp_loss_pct": temp_loss_pct,
    }


async def fetch_pvgis(latitude: float, longitude: float, tilt: float, azimuth: float,
                      mounting: str = DEFAULT_MOUNTING) -> dict:
    params = {
        "lat": latitude,
        "lon": longitude,
        "angle": tilt,
        "aspect": azimuth,
        # Does not affect H(i), only the temperature loss reported with it.
        "mountingplace": mounting,
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


async def get_irradiance(db: Session, latitude: float, longitude: float, tilt: float,
                         azimuth: float, mounting: str = DEFAULT_MOUNTING) -> dict:
    """Irradiance for a site: cache, then PVGIS, then the static fallback.

    Commits the session when it writes a cache row, so call it before modifying
    any other objects in the same session.
    """
    lat_key, lon_key, tilt_key, azimuth_key, mounting = cache_key(latitude, longitude, tilt, azimuth, mounting)

    cached = (
        db.query(IrradianceCache)
        .filter_by(lat_key=lat_key, lon_key=lon_key, tilt_key=tilt_key,
                   azimuth_key=azimuth_key, mounting=mounting)
        .first()
    )
    if cached:
        return _with_relative_sd({
            "monthly_h": json.loads(cached.monthly_h_json),
            "h_annual": cached.h_annual,
            "source": "pvgis",
            "radiation_db": cached.radiation_db,
            "e_annual": cached.e_annual,
            "sd_annual": cached.sd_annual,
            "temp_loss_pct": cached.temp_loss_pct,
        })

    # Query at the cell's own coordinates rather than the project's, so a cached
    # value never depends on which project in the cell happened to fetch it first.
    try:
        irradiance = parse_pvgis(await fetch_pvgis(lat_key / 100, lon_key / 100, tilt_key, azimuth_key, mounting))
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
        mounting=mounting,
        monthly_h_json=json.dumps(irradiance["monthly_h"]),
        h_annual=irradiance["h_annual"],
        radiation_db=irradiance["radiation_db"],
        e_annual=irradiance["e_annual"],
        sd_annual=irradiance["sd_annual"],
        temp_loss_pct=irradiance["temp_loss_pct"],
    ))
    try:
        db.commit()
    except IntegrityError:
        # A concurrent calculation cached this cell first. Same query, same data.
        db.rollback()
    return _with_relative_sd(irradiance)
