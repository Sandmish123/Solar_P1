import json
import os
import tempfile
from pathlib import Path

import pytest

# Bind the app to a throwaway SQLite file before anything imports the engine.
# Hard assignment, not setdefault: the schema fixture drops tables, and that must
# never touch a DATABASE_URL inherited from the shell.
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'test.db')}"

from fastapi.testclient import TestClient  # noqa: E402

from app.database.session import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.building_cache import BuildingCache  # noqa: E402,F401  (registers the table)
from app.models.irradiance_cache import IrradianceCache  # noqa: E402,F401  (registers the table)
from app.models.solar_project import SolarProject  # noqa: E402,F401  (registers the table)
from app.services import buildings, irradiance  # noqa: E402

# Real PVGIS v5_3 PVcalc response for the Gurugram cell (28.51, 77.06, 25 deg, south).
PVGIS_GURUGRAM = json.loads((Path(__file__).parent / "fixtures" / "pvgis_gurugram.json").read_text())
# Real Overpass response for the reference site's cell (28.5076, 77.0618, r=150 m).
OVERPASS_GURUGRAM = json.loads((Path(__file__).parent / "fixtures" / "overpass_gurugram.json").read_text())


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def offline_pvgis(monkeypatch):
    """No test reaches the network. Returns the list of (lat, lon, tilt, azimuth) fetched."""
    calls = []

    async def fake_fetch(latitude, longitude, tilt, azimuth):
        calls.append((latitude, longitude, tilt, azimuth))
        return PVGIS_GURUGRAM

    monkeypatch.setattr(irradiance, "fetch_pvgis", fake_fetch)
    return calls


@pytest.fixture(autouse=True)
def offline_overpass(monkeypatch):
    """No test reaches Overpass. Returns the list of (lat, lon, radius) fetched."""
    calls = []

    async def fake_fetch(latitude, longitude, radius_m):
        calls.append((latitude, longitude, radius_m))
        return OVERPASS_GURUGRAM

    monkeypatch.setattr(buildings, "fetch_buildings", fake_fetch)
    return calls


@pytest.fixture
def pvgis_payload():
    return PVGIS_GURUGRAM


@pytest.fixture
def overpass_payload():
    return OVERPASS_GURUGRAM


@pytest.fixture
def gurugram_irradiance():
    return irradiance.parse_pvgis(PVGIS_GURUGRAM)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def project_payload():
    """The reference Gurugram project the calculation tests are pinned to."""
    return {
        "project_name": "New Solar Project",
        "client_name": "Mr. Gurpreet",
        "site_address": "Gurugram, Haryana",
        "latitude": 28.507563,
        "longitude": 77.061796,
        "date": "20/7/2026",
        "num_panels": 15,
        "panel_wattage": 635,
        "panel_model": "Luminous Solar LUM 635TG132 Bifi-GL",
        "inverter_model": "Luminous NXI 320",
        "roof_area_sqm": 189,
        "degradation_rate": 0.7,
        "temp_loss_pct": 11.5,
        "shading_loss_pct": 0.0,
        "soiling_loss_pct": 3.0,
        "inverter_loss_pct": 3.0,
        "mismatch_loss_pct": 2.0,
        "dc_wiring_loss_pct": 2.0,
        "ac_wiring_loss_pct": 0.0,
        "system_cost_inr": 523_875,  # Rs. 55,000/kWp
    }
