import pytest

from app.config import DEFAULT_SECRET_KEY, Settings
from app.services.auth import MAX_PASSWORD_BYTES, hash_password, verify_password
from tests.conftest import ORG_A_EMAIL, TEST_PASSWORD


# --- password handling -----------------------------------------------------

def test_password_round_trip():
    stored = hash_password("a-real-password")
    assert stored != "a-real-password"          # never stored in the clear
    assert verify_password("a-real-password", stored)
    assert not verify_password("a-real-passworD", stored)


def test_each_hash_is_salted():
    assert hash_password("same") != hash_password("same")


def test_a_corrupt_hash_fails_closed():
    assert verify_password("anything", "not-a-bcrypt-hash") is False


# --- sign in ---------------------------------------------------------------

def test_login_and_me(anonymous_client):
    response = anonymous_client.post("/api/auth/login", json={"email": ORG_A_EMAIL, "password": TEST_PASSWORD})
    assert response.status_code == 200
    assert response.json()["email"] == ORG_A_EMAIL
    assert "password_hash" not in response.json()

    assert anonymous_client.get("/api/auth/me").json()["email"] == ORG_A_EMAIL


def test_login_is_case_insensitive_on_email(anonymous_client):
    assert anonymous_client.post(
        "/api/auth/login", json={"email": ORG_A_EMAIL.upper(), "password": TEST_PASSWORD}
    ).status_code == 200


@pytest.mark.parametrize("email, password", [
    (ORG_A_EMAIL, "wrong-password"),
    ("nobody@example.com", TEST_PASSWORD),
])
def test_bad_credentials_give_one_indistinguishable_error(anonymous_client, email, password):
    response = anonymous_client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    # The same message either way: never confirm which addresses have accounts.
    assert response.json()["detail"] == "Incorrect email or password"


def test_password_beyond_the_bcrypt_limit_is_rejected(anonymous_client):
    # bcrypt truncates at 72 bytes, which would make two long passwords equivalent.
    response = anonymous_client.post(
        "/api/auth/login", json={"email": ORG_A_EMAIL, "password": "x" * (MAX_PASSWORD_BYTES + 1)}
    )
    assert response.status_code == 422


def test_logout_ends_the_session(anonymous_client):
    # A real sign-in, not the shared session cookie the `client` fixture injects:
    # logout works by expiring the cookie the server issued.
    anonymous_client.post("/api/auth/login", json={"email": ORG_A_EMAIL, "password": TEST_PASSWORD})
    assert anonymous_client.get("/api/auth/me").status_code == 200

    assert anonymous_client.post("/api/auth/logout").status_code == 204
    assert anonymous_client.get("/api/auth/me").status_code == 401


# --- everything requires a session -----------------------------------------

@pytest.mark.parametrize("method, path", [
    ("get", "/api/projects/"),
    ("post", "/api/projects/"),
    ("get", "/api/projects/1"),
    ("put", "/api/projects/1"),
    ("delete", "/api/projects/1"),
    ("post", "/api/projects/1/calculate"),
    ("get", "/api/projects/1/report/pdf"),
    ("get", "/api/geospatial/building?latitude=28.5&longitude=77.06"),
    ("get", "/api/auth/me"),
])
def test_anonymous_requests_are_rejected(anonymous_client, method, path):
    assert getattr(anonymous_client, method)(path).status_code == 401


def test_health_stays_public(anonymous_client):
    # The Render health check has no cookie.
    assert anonymous_client.get("/api/health").status_code == 200


# --- tenant isolation: the test that must never be deleted -----------------

def test_one_firm_cannot_reach_another_firms_project(client, other_org_client, project_payload):
    created = client.post("/api/projects/", json=project_payload)
    project_id = created.json()["id"]
    client.post(f"/api/projects/{project_id}/calculate")

    # 404, not 403: Org B must not even learn that this project exists.
    assert other_org_client.get(f"/api/projects/{project_id}").status_code == 404
    assert other_org_client.put(f"/api/projects/{project_id}", json=project_payload).status_code == 404
    assert other_org_client.post(f"/api/projects/{project_id}/calculate").status_code == 404
    assert other_org_client.get(f"/api/projects/{project_id}/report/pdf").status_code == 404
    assert other_org_client.delete(f"/api/projects/{project_id}").status_code == 404

    # And it is still there afterwards.
    assert client.get(f"/api/projects/{project_id}").status_code == 200


def test_listings_and_search_are_scoped(client, other_org_client, project_payload):
    client.post("/api/projects/", json={**project_payload, "project_name": "Org A Only Project"})

    visible = [p["project_name"] for p in other_org_client.get("/api/projects/").json()]
    assert "Org A Only Project" not in visible
    assert other_org_client.get("/api/projects/", params={"search": "Org A Only"}).json() == []


def test_a_new_project_belongs_to_the_creators_org(client, accounts, project_payload):
    created = client.post("/api/projects/", json=project_payload).json()
    assert created["org_id"] == accounts["org_a"]


def test_org_id_cannot_be_set_by_the_client(client, accounts, project_payload):
    # Even if a caller supplies one, the session decides ownership.
    created = client.post("/api/projects/", json={**project_payload, "org_id": accounts["org_b"]}).json()
    assert created["org_id"] == accounts["org_a"]


# --- configuration ---------------------------------------------------------

def test_production_refuses_the_default_secret_key():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(APP_ENV="production", SECRET_KEY=DEFAULT_SECRET_KEY)

    assert Settings(APP_ENV="production", SECRET_KEY="a-real-secret").is_production
    assert Settings(APP_ENV="development", SECRET_KEY=DEFAULT_SECRET_KEY).SECRET_KEY == DEFAULT_SECRET_KEY
