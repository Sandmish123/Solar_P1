import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

# Bind the app to a throwaway SQLite file before anything imports the engine.
# Hard assignment, not setdefault: the schema fixture drops tables, and that must
# never touch a DATABASE_URL inherited from the shell.
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'test.db')}"

from fastapi.testclient import TestClient  # noqa: E402

from app.database.session import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.building_cache import BuildingCache  # noqa: E402,F401  (registers the table)
from app.models.components import InverterModel, PanelModel  # noqa: E402,F401  (registers the tables)
from app.models.irradiance_cache import IrradianceCache  # noqa: E402,F401  (registers the table)
from app.models.organisation import Organisation  # noqa: E402
from app.models.solar_project import SolarProject  # noqa: E402,F401  (registers the table)
from app.models.user import User  # noqa: E402
from app.services import buildings, irradiance  # noqa: E402
from app.services.auth import hash_password  # noqa: E402

# Two organisations, so tenant isolation is testable rather than assumed.
TEST_PASSWORD = "correct-horse-battery"
ORG_A_EMAIL = "a@example.com"
ORG_B_EMAIL = "b@example.com"

# Real PVGIS v5_3 PVcalc response for the Gurugram cell (28.51, 77.06, 25 deg, south).
PVGIS_GURUGRAM = json.loads((Path(__file__).parent / "fixtures" / "pvgis_gurugram.json").read_text())
# Real Overpass response for the reference site's cell (28.5076, 77.0618, r=150 m).
OVERPASS_GURUGRAM = json.loads((Path(__file__).parent / "fixtures" / "overpass_gurugram.json").read_text())


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="session")
def accounts(_schema):
    """Two firms, one user each. Returns their organisation ids."""
    session = SessionLocal()
    try:
        org_a, org_b = Organisation(name="Org A"), Organisation(name="Org B")
        session.add_all([org_a, org_b])
        session.flush()
        password_hash = hash_password(TEST_PASSWORD)
        session.add_all([
            User(org_id=org_a.id, email=ORG_A_EMAIL, password_hash=password_hash, role="admin"),
            User(org_id=org_b.id, email=ORG_B_EMAIL, password_hash=password_hash, role="member"),
        ])
        session.commit()
        return {"org_a": org_a.id, "org_b": org_b.id}
    finally:
        session.close()


def _signed_in_cookies(email):
    """Sign in once and keep the cookie. bcrypt is deliberately slow, so logging in
    per test would add roughly 30 seconds to the suite; the session cookie is signed
    and stateless, so it can be replayed on a fresh client."""
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
        assert response.status_code == 200, response.text
        return dict(test_client.cookies)


@pytest.fixture(scope="session")
def _org_a_cookies(accounts):
    return _signed_in_cookies(ORG_A_EMAIL)


@pytest.fixture(scope="session")
def _org_b_cookies(accounts):
    return _signed_in_cookies(ORG_B_EMAIL)


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
def client(_org_a_cookies):
    """Signed in as Org A. Every existing test uses this."""
    with TestClient(app) as test_client:
        test_client.cookies.update(_org_a_cookies)
        yield test_client


@pytest.fixture
def other_org_client(_org_b_cookies):
    """Signed in as Org B, for proving isolation."""
    with TestClient(app) as test_client:
        test_client.cookies.update(_org_b_cookies)
        yield test_client


@pytest.fixture
def anonymous_client(accounts):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_panel(client):
    """Creates a catalog panel owned by Org A. Unique model name per call, because
    (org_id, manufacturer, model) is unique."""
    def _make(**overrides):
        payload = {
            "manufacturer": "TestCo",
            "model": f"P-{uuid4().hex[:8]}",
            "wp": 635,
            "almm_listed": True,
            "dcr": True,
            "datasheet_verified": True,
        }
        payload.update(overrides)
        response = client.post("/api/catalog/panels", json=payload)
        assert response.status_code == 201, response.text
        return response.json()
    return _make


@pytest.fixture
def make_inverter(client):
    def _make(**overrides):
        payload = {
            "manufacturer": "TestCo",
            "model": f"I-{uuid4().hex[:8]}",
            "ac_kw": 5.0,
            "datasheet_verified": True,
        }
        payload.update(overrides)
        response = client.post("/api/catalog/inverters", json=payload)
        assert response.status_code == 201, response.text
        return response.json()
    return _make


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
