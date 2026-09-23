import json
import math
import shutil
import subprocess
import textwrap
from datetime import date

import pytest

from app.calculations.solar_position import (
    month_of_year_day,
    panel_bearing,
    sun_position,
    timezone_offset_hours,
)

GURUGRAM = (28.507563, 77.061796)

# (label, date, minutes past local midnight)
CASES = [
    ("summer solstice noon", date(2026, 6, 21), 12 * 60),
    ("winter solstice noon", date(2026, 12, 21), 12 * 60),
    ("equinox noon", date(2026, 3, 20), 12 * 60),
    ("summer dawn", date(2026, 6, 21), 6 * 60),
    ("winter afternoon", date(2026, 12, 21), 15 * 60 + 30),
]


def test_solstice_elevations_match_hand_calculation():
    latitude, longitude = GURUGRAM
    # Midday elevation = 90 - |latitude - declination|, declination +-23.44.
    summer, _ = sun_position(date(2026, 6, 21).timetuple().tm_yday, 12 * 60 + 26, latitude, longitude)
    winter, _ = sun_position(date(2026, 12, 21).timetuple().tm_yday, 12 * 60 + 26, latitude, longitude)

    assert summer == pytest.approx(90 - abs(latitude - 23.44), abs=0.5)
    assert winter == pytest.approx(90 - abs(latitude + 23.44), abs=0.5)


def test_azimuth_is_a_compass_bearing():
    latitude, longitude = GURUGRAM
    # Winter, not summer: at the summer solstice the midday sun is 5 degrees from
    # the zenith here, where azimuth swings ~25 degrees in ten minutes and any
    # assertion about it is meaningless.
    _, noon = sun_position(355, 12 * 60 + 23, latitude, longitude)
    _, morning = sun_position(355, 9 * 60, latitude, longitude)
    _, evening = sun_position(355, 16 * 60, latitude, longitude)

    assert noon == pytest.approx(180, abs=3)   # south at solar noon
    assert morning < 180 < evening             # east in the morning, west in the evening


def test_sun_is_below_the_horizon_at_night():
    latitude, longitude = GURUGRAM
    elevation, _ = sun_position(355, 2 * 60, latitude, longitude)
    assert elevation < 0


def test_panel_bearing_converts_pvgis_convention():
    assert panel_bearing(0) == 180     # south
    assert panel_bearing(-90) == 90    # east
    assert panel_bearing(90) == 270    # west


def test_timezone_offset_keeps_ist_for_india():
    assert timezone_offset_hours(77.06) == 5.5
    assert timezone_offset_hours(0.0) == 0.0


def test_month_of_year_day():
    assert month_of_year_day(1) == 1
    assert month_of_year_day(32) == 2
    assert month_of_year_day(365) == 12


@pytest.mark.skipif(not shutil.which("node"), reason="node is needed to run the browser solver")
def test_python_and_javascript_solvers_agree():
    """The 3D view keeps its own solver so the time slider stays local. This is the
    guard that the two never drift apart."""
    script = textwrap.dedent("""
        const fs = require('fs');
        const mapManager = eval(fs.readFileSync('frontend/js/3d-model.js', 'utf8') + ';mapManager');
        const cases = JSON.parse(process.argv[1]);
        console.log(JSON.stringify(cases.map(([y, m, d, minutes, lat, lon]) =>
            mapManager.solarPosition(new Date(y, m - 1, d), minutes, lat, lon))));
    """)
    payload = [[d.year, d.month, d.day, minutes, GURUGRAM[0], GURUGRAM[1]] for _, d, minutes in CASES]
    result = subprocess.run(
        ["node", "-e", script, json.dumps(payload)],
        capture_output=True, text=True, cwd=".",
    )
    assert result.returncode == 0, result.stderr
    from_js = json.loads(result.stdout)

    for (label, day, minutes), js in zip(CASES, from_js):
        elevation, azimuth = sun_position(day.timetuple().tm_yday, minutes, *GURUGRAM)
        assert elevation == pytest.approx(js["elevation"], abs=1e-6), label
        # Compare azimuths on the circle, so 359.9 and 0.1 count as close.
        delta = abs((azimuth - js["azimuth"] + 180) % 360 - 180)
        assert delta < 1e-6, f"{label}: {azimuth} vs {js['azimuth']}"
