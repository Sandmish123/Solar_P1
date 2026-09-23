"""OSM building footprints around a site, from Overpass, with a DB cache.

Failure behaviour: any error returns None, meaning "geometry unknown". The caller
then leaves shading to the operator rather than inventing a number. There is no
fallback geometry, because a made-up skyline is worse than no estimate.
"""
import asyncio
import json
import logging

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.building_cache import BuildingCache

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Overpass is a free shared service and much slower than PVGIS; this only runs when
# the operator opts into automatic shading, and the result is cached.
OVERPASS_TIMEOUT_S = 15.0
# The public instance returns 504 under load often enough that a single attempt
# usually fails; one retry roughly doubles the hit rate. Worst case stays bounded
# at about 31 s, and only on the opt-in shading path.
OVERPASS_ATTEMPTS = 2
OVERPASS_RETRY_DELAY_S = 1.5
SEARCH_RADIUS_M = 150
LEVEL_HEIGHT_M = 3.0
# Most Indian buildings in OSM carry no height and no building:levels. Guessing low
# would understate shading and overstate generation, so assume two storeys and
# report how many heights were assumed rather than silently flattening the skyline.
ASSUMED_HEIGHT_M = 6.0


def cache_key(latitude: float, longitude: float, radius_m: int) -> tuple:
    return round(latitude * 10000), round(longitude * 10000), int(radius_m)


def _height_of(tags: dict) -> tuple:
    """(height_m, source) from OSM tags."""
    raw_height = str(tags.get("height", "")).replace("m", "").strip()
    try:
        height = float(raw_height)
        if height > 0:
            return height, "tag"
    except ValueError:
        pass
    try:
        levels = float(tags.get("building:levels"))
        if levels > 0:
            return levels * LEVEL_HEIGHT_M, "levels"
    except (TypeError, ValueError):
        pass
    return ASSUMED_HEIGHT_M, "assumed"


def parse_buildings(payload: dict) -> list:
    """Closed footprints with a height. Raises ValueError if the body is not Overpass."""
    try:
        elements = payload["elements"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unexpected Overpass response shape: {exc!r}") from exc

    buildings = []
    for element in elements:
        geometry = element.get("geometry") or []
        if len(geometry) < 3:
            continue  # relations from `out geom` carry members, not a ring: skipped
        height, source = _height_of(element.get("tags") or {})
        buildings.append({
            "polygon": [[point["lon"], point["lat"]] for point in geometry],
            "height_m": height,
            "height_source": source,
        })
    return buildings


async def fetch_buildings(latitude: float, longitude: float, radius_m: int) -> dict:
    query = (
        f"[out:json][timeout:{int(OVERPASS_TIMEOUT_S)}];"
        f'way(around:{radius_m},{latitude},{longitude})["building"];'
        f"out geom;"
    )
    last_error = None
    for attempt in range(OVERPASS_ATTEMPTS):
        if attempt:
            await asyncio.sleep(OVERPASS_RETRY_DELAY_S)
        try:
            async with httpx.AsyncClient(timeout=OVERPASS_TIMEOUT_S) as client:
                response = await client.post(
                    OVERPASS_URL,
                    content=query,
                    headers={"Content-Type": "text/plain", "User-Agent": "Solar-P1/1.0"},
                )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            last_error = exc
            logger.info("Overpass attempt %d/%d failed: %r", attempt + 1, OVERPASS_ATTEMPTS, exc)
    raise last_error


async def get_buildings(db: Session, latitude: float, longitude: float, radius_m: int = SEARCH_RADIUS_M):
    """Buildings around a site, or None if Overpass could not be reached.

    Commits the session when it writes a cache row, so call it before modifying
    other objects in that session.
    """
    lat_key, lon_key, radius = cache_key(latitude, longitude, radius_m)

    cached = db.query(BuildingCache).filter_by(lat_key=lat_key, lon_key=lon_key, radius_m=radius).first()
    if cached:
        return json.loads(cached.buildings_json)

    # Query at the cell's own coordinates so a cached answer does not depend on
    # which project in the cell happened to fetch it.
    try:
        buildings = parse_buildings(await fetch_buildings(lat_key / 10000, lon_key / 10000, radius))
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "Overpass unavailable for cell (%s, %s) r=%sm, shading not estimated: %r",
            lat_key / 10000, lon_key / 10000, radius, exc,
        )
        return None

    db.add(BuildingCache(
        lat_key=lat_key, lon_key=lon_key, radius_m=radius,
        buildings_json=json.dumps(buildings),
    ))
    try:
        db.commit()
    except IntegrityError:
        # A concurrent calculation cached this cell first. Same query, same data.
        db.rollback()
    return buildings
