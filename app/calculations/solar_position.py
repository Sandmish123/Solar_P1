"""Solar position, ported from the sun solver in frontend/js/3d-model.js.

Pure functions, angles in degrees. The 3D view keeps its own copy so dragging the
time slider stays local; `tests/test_solar_position.py` runs both against each
other so the two cannot drift apart.

Sun azimuth is a compass bearing: 0 = north, 90 = east, 180 = south, 270 = west.
Panel azimuth elsewhere in the app follows PVGIS (0 = south, -90 = east), which
`panel_bearing` converts.
"""
import math
from datetime import date, timedelta

# A non-leap reference year, so day-of-year maps to a month the same way every year.
_REFERENCE_YEAR = 2001
_MONTH_BY_DAY_OF_YEAR = [
    (date(_REFERENCE_YEAR, 1, 1) + timedelta(days=offset)).month for offset in range(365)
]


def month_of_year_day(day_of_year: int) -> int:
    """1-based day of year -> 1-based month."""
    return _MONTH_BY_DAY_OF_YEAR[min(day_of_year, 365) - 1]


def declination_deg(day_of_year: int) -> float:
    return 23.44 * math.sin((2 * math.pi / 365) * (day_of_year - 81))


def equation_of_time_min(day_of_year: int) -> float:
    b = 2 * math.pi * (day_of_year - 81) / 364
    return 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)


def timezone_offset_hours(longitude: float) -> float:
    # The proposals are in India; preserve its UTC+05:30 civil time.
    if 60 <= longitude <= 100:
        return 5.5
    # math.floor(x + 0.5), not round(): Python rounds halves to even, JavaScript's
    # Math.round rounds them up, and the two must agree.
    return math.floor(longitude / 15 * 2 + 0.5) / 2


def sun_position(day_of_year: int, minutes: float, latitude: float, longitude: float) -> tuple:
    """(elevation, azimuth) in degrees for local civil time `minutes` past midnight."""
    declination = declination_deg(day_of_year)
    solar_minutes = (
        minutes
        + equation_of_time_min(day_of_year)
        + 4 * longitude
        - timezone_offset_hours(longitude) * 60
    )
    hour_angle = math.radians((solar_minutes - 720) / 4)
    lat = math.radians(latitude)
    dec = math.radians(declination)

    elevation = math.degrees(math.asin(
        max(-1.0, min(1.0, math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(hour_angle)))
    ))
    azimuth = (math.degrees(math.atan2(
        math.sin(hour_angle),
        math.cos(hour_angle) * math.sin(lat) - math.tan(dec) * math.cos(lat),
    )) + 180 + 360) % 360
    return elevation, azimuth


def panel_bearing(azimuth_deg: float) -> float:
    """PVGIS panel azimuth (0 south, -90 east, +90 west) -> compass bearing."""
    return (180 + azimuth_deg) % 360
