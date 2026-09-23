"""Shading of the array by neighbouring buildings, from OSM footprints.

Method: collapse the surrounding geometry into a horizon profile once - the highest
obstruction elevation in each 1-degree slice of azimuth - then sweep the sun path
for a year against it. Each sample is weighted by the beam irradiance it would put
on the tilted plane, so a blocked midday hour in May counts for more than a blocked
minute at dawn.

Pure functions, no DB or I/O, like the other modules in this package.

Known limits, all deliberate:
- Treats all irradiance as beam. Diffuse light still arrives when the sun is
  blocked, so the figure overstates the real loss. That errs towards under-promising
  generation, which is the direction this project chose in Phase 1.
- The array is a single point at roof height: no row-to-row self-shading, and no
  spatial variation across a large roof.
- OSM heights are often missing and then estimated from building:levels, so the
  result is only as good as the local mapping.
"""
import math

from app.calculations.solar_position import month_of_year_day, panel_bearing, sun_position

AZIMUTH_BINS = 360          # one bin per degree of compass bearing
SAMPLE_MINUTES = 30         # half-hourly sun path
MIN_DISTANCE_M = 1.0        # ignore geometry we are practically standing on
EARTH_RADIUS_M = 6371000.0
DEFAULT_ARRAY_HEIGHT_M = 3.0   # single storey, when OSM has no host building


def local_xy(latitude: float, longitude: float, origin_lat: float, origin_lon: float) -> tuple:
    """Metres (east, north) from the origin. Equirectangular: exact enough over the
    ~150 m that matters here."""
    east = math.radians(longitude - origin_lon) * EARTH_RADIUS_M * math.cos(math.radians(origin_lat))
    north = math.radians(latitude - origin_lat) * EARTH_RADIUS_M
    return east, north


def point_in_polygon(x: float, y: float, ring: list) -> bool:
    """Ray casting. `ring` is [(x, y), ...]."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y):
            crossing_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if crossing_x > x:
                inside = not inside
    return inside


def _ring_xy(building: dict, origin_lat: float, origin_lon: float) -> list:
    return [local_xy(lat, lon, origin_lat, origin_lon) for lon, lat in building["polygon"]]


def _bearing_deg(x: float, y: float) -> float:
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _ray_distance(x1: float, y1: float, dx: float, dy: float, bearing_deg: float):
    """Distance from the array to the wall segment along a bearing, or None if the
    ray misses it. Exact, so a wall fills every azimuth bin it really spans."""
    theta = math.radians(bearing_deg)
    dir_x, dir_y = math.sin(theta), math.cos(theta)
    denom = dir_x * dy - dir_y * dx
    if abs(denom) < 1e-12:
        return None  # ray parallel to the wall
    distance = (x1 * dy - y1 * dx) / denom
    along = (x1 * dir_y - y1 * dir_x) / denom
    if distance <= MIN_DISTANCE_M or not (-1e-9 <= along <= 1 + 1e-9):
        return None
    return distance


def horizon_profile(buildings: list, origin_lat: float, origin_lon: float, array_height_m: float) -> list:
    """Highest obstruction elevation (degrees) per azimuth bin, seen from the array."""
    horizon = [0.0] * AZIMUTH_BINS

    for building in buildings:
        rise = building["height_m"] - array_height_m
        if rise <= 0:
            continue  # at or below the panels: cannot shade them

        ring = _ring_xy(building, origin_lat, origin_lon)
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            dx, dy = x2 - x1, y2 - y1
            start = _bearing_deg(x1, y1)
            # Signed shorter arc the wall spans, -180..180.
            span = (_bearing_deg(x2, y2) - start + 540) % 360 - 180

            def raise_bin(bin_index, distance):
                elevation = math.degrees(math.atan2(rise, distance))
                if elevation > horizon[bin_index]:
                    horizon[bin_index] = elevation

            # Every bin the wall covers, measured to the wall itself rather than to
            # sampled points: point sampling left gaps that the sun shone through.
            for step in range(int(abs(span)) + 2):
                bearing = (start + math.copysign(min(step, abs(span)), span)) % 360
                bin_index = int(bearing) % AZIMUTH_BINS
                distance = _ray_distance(x1, y1, dx, dy, bin_index + 0.5)
                if distance is not None:
                    raise_bin(bin_index, distance)

            # The end bins can be clipped by the bin-centre ray; seed them from the
            # corners so a wall is never missed entirely.
            for x, y in ((x1, y1), (x2, y2)):
                corner_distance = math.hypot(x, y)
                if corner_distance > MIN_DISTANCE_M:
                    raise_bin(int(_bearing_deg(x, y)) % AZIMUTH_BINS, corner_distance)

    return horizon


def shading_from_horizon(horizon: list, latitude: float, longitude: float, tilt_deg: float, azimuth_deg: float) -> dict:
    """Beam-weighted fraction of the year's irradiance blocked by the horizon."""
    bearing = panel_bearing(azimuth_deg)
    tilt = math.radians(tilt_deg)
    sin_tilt, cos_tilt = math.sin(tilt), math.cos(tilt)

    total = [0.0] * 12
    blocked = [0.0] * 12

    for day in range(1, 366):
        month = month_of_year_day(day) - 1
        for minutes in range(0, 1440, SAMPLE_MINUTES):
            elevation, azimuth = sun_position(day, minutes, latitude, longitude)
            if elevation <= 0:
                continue
            elevation_rad = math.radians(elevation)
            # Cosine of the angle between the sun and the panel normal.
            incidence = (
                math.cos(elevation_rad) * sin_tilt * math.cos(math.radians(azimuth - bearing))
                + math.sin(elevation_rad) * cos_tilt
            )
            if incidence <= 0:
                continue  # sun is behind the panel
            total[month] += incidence
            if elevation < horizon[int(azimuth) % AZIMUTH_BINS]:
                blocked[month] += incidence

    year_total = sum(total)
    if year_total <= 0:
        return {"annual_pct": 0.0, "monthly_pct": [0.0] * 12}

    return {
        "annual_pct": round(100 * sum(blocked) / year_total, 2),
        "monthly_pct": [
            round(100 * b / t, 2) if t > 0 else 0.0 for b, t in zip(blocked, total)
        ],
    }


def find_host_height(buildings: list, latitude: float, longitude: float):
    """Height of the building the array stands on, or None if it is not mapped."""
    for building in buildings:
        if point_in_polygon(0.0, 0.0, _ring_xy(building, latitude, longitude)):
            return building["height_m"]
    return None


def compute_shading(buildings: list, latitude: float, longitude: float, tilt_deg: float,
                    azimuth_deg: float, array_height_m: float) -> dict:
    """Shading loss for an array, given the buildings around it.

    `buildings` are [{"polygon": [(lon, lat), ...], "height_m": float}]. The one the
    array stands on is excluded: its own roof does not shade the panels on it.
    """
    neighbours = [
        building for building in buildings
        if not point_in_polygon(0.0, 0.0, _ring_xy(building, latitude, longitude))
    ]
    obstructing = [b for b in neighbours if b["height_m"] > array_height_m]

    horizon = horizon_profile(obstructing, latitude, longitude, array_height_m)
    result = shading_from_horizon(horizon, latitude, longitude, tilt_deg, azimuth_deg)
    result["neighbour_count"] = len(obstructing)
    # OSM often omits heights; say how many were guessed so the operator can judge.
    result["heights_assumed"] = sum(1 for b in obstructing if b.get("height_source") == "assumed")
    result["horizon_max_deg"] = round(max(horizon), 2) if horizon else 0.0
    return result
