import math

import pytest

from app.calculations.shading import (
    EARTH_RADIUS_M,
    compute_shading,
    find_host_height,
    horizon_profile,
    point_in_polygon,
    shading_from_horizon,
)

LAT, LON = 28.507563, 77.061796
ARRAY_HEIGHT_M = 3.0


def offset(east_m, north_m):
    return (
        LON + math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(LAT)))),
        LAT + math.degrees(north_m / EARTH_RADIUS_M),
    )


def block(bearing_deg, near_face_m, height_m, width_m=20, depth_m=10, height_source="tag"):
    """A rectangle whose near face sits `near_face_m` from the array along a bearing."""
    bearing = math.radians(bearing_deg)
    centre = near_face_m + depth_m / 2
    cx, cy = math.sin(bearing) * centre, math.cos(bearing) * centre
    polygon = []
    for dx, dy in [(-width_m / 2, -depth_m / 2), (width_m / 2, -depth_m / 2),
                   (width_m / 2, depth_m / 2), (-width_m / 2, depth_m / 2)]:
        polygon.append(offset(
            cx + dx * math.cos(bearing) + dy * math.sin(bearing),
            cy - dx * math.sin(bearing) + dy * math.cos(bearing),
        ))
    return {"polygon": polygon, "height_m": height_m, "height_source": height_source}


def run(buildings, tilt=25, azimuth=0, array_height=ARRAY_HEIGHT_M):
    return compute_shading(buildings, LAT, LON, tilt, azimuth, array_height)


# --- geometry primitives ---------------------------------------------------

def test_point_in_polygon():
    square = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    assert point_in_polygon(0, 0, square)
    assert not point_in_polygon(2, 0, square)
    assert not point_in_polygon(0, 5, square)


def test_horizon_angle_matches_trigonometry():
    # 10 m tall, near face 10 m away, array at 3 m: atan(7/10) = 34.99 degrees.
    horizon = horizon_profile([block(180, 10, 10)], LAT, LON, ARRAY_HEIGHT_M)
    assert max(horizon) == pytest.approx(34.99, abs=0.6)
    # ...and it sits in the southern bins.
    assert horizon[180] > 30
    assert horizon[0] == 0


# --- shading behaviour -----------------------------------------------------

def test_no_neighbours_means_no_shading():
    result = run([])
    assert result["annual_pct"] == 0.0
    assert result["neighbour_count"] == 0


def test_south_shades_far_more_than_north():
    south = run([block(180, 10, 10)])
    north = run([block(0, 10, 10)])
    # At 28.5N the sun is in the south; a block due north barely matters.
    assert south["annual_pct"] > 0
    assert north["annual_pct"] < south["annual_pct"] / 5


def test_winter_is_shaded_more_than_summer():
    monthly = run([block(180, 10, 10)])["monthly_pct"]
    assert monthly[11] > monthly[5]   # December worse than June: lower sun


def test_uniform_horizon_is_worst_at_the_solstice():
    # A symmetric obstruction isolates the sun model from the geometry.
    monthly = shading_from_horizon([30.0] * 360, LAT, LON, 25, 0)["monthly_pct"]
    assert monthly[11] > monthly[0] > monthly[5]


def test_closer_and_taller_shade_more():
    by_distance = [run([block(180, d, 10)])["annual_pct"] for d in (5, 10, 20)]
    by_height = [run([block(180, 10, h)])["annual_pct"] for h in (10, 20, 40)]
    assert by_distance == sorted(by_distance, reverse=True)
    assert by_height == sorted(by_height)


def test_geometry_at_or_below_the_array_cannot_shade():
    result = run([block(180, 10, ARRAY_HEIGHT_M)])
    assert result["neighbour_count"] == 0
    assert result["annual_pct"] == 0.0


def test_host_building_is_excluded():
    host = {"polygon": [offset(-8, -8), offset(8, -8), offset(8, 8), offset(-8, 8)],
            "height_m": 12, "height_source": "tag"}
    assert find_host_height([host], LAT, LON) == 12
    result = run([host])
    assert result["neighbour_count"] == 0    # your own roof does not shade your panels
    assert result["annual_pct"] == 0.0


def test_find_host_height_returns_none_when_unmapped():
    assert find_host_height([block(180, 10, 10)], LAT, LON) is None


def test_assumed_heights_are_reported():
    result = run([block(180, 10, 10, height_source="assumed"), block(90, 10, 10, height_source="tag")])
    assert result["neighbour_count"] == 2
    assert result["heights_assumed"] == 1


def test_dense_surroundings_produce_a_large_loss():
    ring = [block(bearing, 12, 15) for bearing in range(0, 360, 45)]
    assert run(ring)["annual_pct"] > 5


def test_panel_orientation_changes_the_loss():
    east_block = [block(90, 8, 15)]
    facing_east = run(east_block, azimuth=-90)["annual_pct"]
    facing_west = run(east_block, azimuth=90)["annual_pct"]
    # A block to the east hurts an east-facing array more than a west-facing one.
    assert facing_east > facing_west
