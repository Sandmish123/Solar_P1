from fastapi import APIRouter, HTTPException, Query
import httpx


router = APIRouter(prefix="/geospatial", tags=["geospatial"])

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def estimated_building(latitude: float, longitude: float):
    return {
        "found": False,
        "source": "Estimated",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [longitude - 0.00012, latitude - 0.00008],
                [longitude + 0.00012, latitude - 0.00008],
                [longitude + 0.00012, latitude + 0.00008],
                [longitude - 0.00012, latitude + 0.00008],
                [longitude - 0.00012, latitude - 0.00008],
            ]],
        },
        "height_m": 3.0,
        "estimated": True,
    }


@router.get("/building")
def get_building_footprint(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
):
    """Return the nearest OSM building footprint for a project coordinate."""
    query = f"""
    [out:json][timeout:15];
    (
      way(around:80,{latitude},{longitude})["building"];
      relation(around:80,{latitude},{longitude})["building"];
    );
    out geom;
    """

    try:
        response = httpx.post(
            OVERPASS_URL,
            content=query,
            headers={"Content-Type": "text/plain", "User-Agent": "Solar-P1/1.0"},
            timeout=20,
        )
        response.raise_for_status()
        elements = response.json().get("elements", [])
    except (httpx.HTTPError, ValueError) as exc:
        return estimated_building(latitude, longitude)

    candidates = []
    for element in elements:
        geometry = element.get("geometry", [])
        if len(geometry) < 3:
            continue
        center_lat = sum(point["lat"] for point in geometry) / len(geometry)
        center_lon = sum(point["lon"] for point in geometry) / len(geometry)
        distance = (center_lat - latitude) ** 2 + (center_lon - longitude) ** 2
        tags = element.get("tags", {})
        try:
            height = float(str(tags.get("height", "")).replace("m", "").strip())
        except ValueError:
            levels = float(tags.get("building:levels", 1))
            height = max(3.0, levels * 3.0)
        candidates.append((distance, element, height))

    if not candidates:
        return estimated_building(latitude, longitude)

    _, element, height = min(candidates, key=lambda item: item[0])
    coordinates = [
        [point["lon"], point["lat"]]
        for point in element["geometry"]
    ]
    if coordinates[0] != coordinates[-1]:
        coordinates.append(coordinates[0])

    return {
        "found": True,
        "source": "OpenStreetMap",
        "osm_id": element.get("id"),
        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
        "height_m": height,
        "estimated": "height" not in element.get("tags", {}),
    }
