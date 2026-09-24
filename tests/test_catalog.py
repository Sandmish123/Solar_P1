import json

import pytest


# --- catalog visibility and ownership --------------------------------------

def test_catalog_starts_visible_and_accepts_additions(client, make_panel):
    panel = make_panel(manufacturer="Acme", wp=550)

    listed = client.get("/api/catalog/panels").json()
    assert any(p["id"] == panel["id"] for p in listed)
    assert panel["org_id"] is not None      # a firm's own row, not a shared one
    assert panel["wp"] == 550


def test_a_firm_cannot_see_another_firms_components(client, other_org_client, make_panel):
    panel = make_panel(manufacturer="PrivateCo")

    visible_to_other = [p["id"] for p in other_org_client.get("/api/catalog/panels").json()]
    assert panel["id"] not in visible_to_other
    assert other_org_client.put(f"/api/catalog/panels/{panel['id']}", json={
        "manufacturer": "PrivateCo", "model": "stolen", "wp": 1,
    }).status_code == 404


def test_own_components_can_be_edited(client, make_panel):
    panel = make_panel(almm_listed=None, dcr=None, datasheet_verified=False)

    updated = client.put(f"/api/catalog/panels/{panel['id']}", json={
        **{k: panel[k] for k in ("manufacturer", "model", "wp")},
        "voc": 41.5, "isc": 18.6, "almm_listed": True, "dcr": True, "datasheet_verified": True,
    }).json()

    assert updated["voc"] == 41.5
    assert updated["almm_listed"] is True
    assert updated["datasheet_verified"] is True


def test_duplicate_model_for_one_firm_is_rejected(client, make_panel):
    panel = make_panel()
    duplicate = client.post("/api/catalog/panels", json={
        "manufacturer": panel["manufacturer"], "model": panel["model"], "wp": 500,
    })
    assert duplicate.status_code == 409


def test_shared_rows_are_read_only(client, db):
    from app.models.components import PanelModel

    shared = PanelModel(org_id=None, manufacturer="SharedCo", model="Seed-1", wp=600)
    db.add(shared)
    db.commit()

    # Visible to the firm...
    assert any(p["id"] == shared.id for p in client.get("/api/catalog/panels").json())
    # ...but not editable, so one firm cannot change a model another is quoting.
    response = client.put(f"/api/catalog/panels/{shared.id}", json={
        "manufacturer": "SharedCo", "model": "Seed-1", "wp": 1,
    })
    assert response.status_code == 403
    assert "shared catalog entry" in response.json()["detail"]


@pytest.mark.parametrize("field, value", [
    ("wp", 0),
    ("voc", -1),
    ("temp_coeff_voc_pct_per_c", 0.5),   # must be negative
    ("efficiency_pct", 150),
])
def test_out_of_range_datasheet_values_are_rejected(client, field, value):
    response = client.post("/api/catalog/panels", json={
        "manufacturer": "TestCo", "model": "bad-values", "wp": 600, field: value,
    })
    assert response.status_code == 422


def test_inverters_work_the_same_way(client, make_inverter):
    inverter = make_inverter(ac_kw=5.5, mppt_count=2)
    listed = client.get("/api/catalog/inverters").json()
    assert any(i["id"] == inverter["id"] and i["mppt_count"] == 2 for i in listed)


def test_catalog_requires_a_session(anonymous_client):
    assert anonymous_client.get("/api/catalog/panels").status_code == 401
    assert anonymous_client.post("/api/catalog/panels", json={}).status_code == 401


# --- compliance drives the subsidy -----------------------------------------

def _calculate(client, payload):
    project_id = client.post("/api/projects/", json=payload).json()["id"]
    return client.post(f"/api/projects/{project_id}/calculate").json()


def test_a_compliant_module_keeps_the_subsidy(client, project_payload, make_panel, make_inverter):
    panel, inverter = make_panel(), make_inverter()

    result = _calculate(client, {
        **project_payload, "panel_model_id": panel["id"], "inverter_model_id": inverter["id"],
    })

    assert result["subsidy_applied_inr"] == 78_000
    assert json.loads(result["compliance_json"]) != []      # the List-II warning still shows
    assert not [i for i in json.loads(result["compliance_json"]) if i["severity"] == "error"]


@pytest.mark.parametrize("overrides, expected_code", [
    ({"dcr": False}, "dcr_not_compliant"),
    ({"dcr": None}, "dcr_unknown"),
    ({"almm_listed": False}, "almm_not_listed"),
    ({"almm_listed": None}, "almm_unknown"),
])
def test_an_ineligible_module_removes_the_subsidy(client, project_payload, make_panel, overrides, expected_code):
    panel = make_panel(**overrides)

    result = _calculate(client, {**project_payload, "panel_model_id": panel["id"]})

    issues = json.loads(result["compliance_json"])
    assert expected_code in {i["code"] for i in issues}
    # Not merely hidden: the payback must not rest on money that will not arrive.
    assert result["subsidy_applied_inr"] == 0
    assert result["net_investment_inr"] == project_payload["system_cost_inr"]


def test_an_ineligible_module_worsens_the_payback(client, project_payload, make_panel):
    compliant = _calculate(client, {**project_payload, "panel_model_id": make_panel()["id"]})
    ineligible = _calculate(client, {**project_payload, "panel_model_id": make_panel(dcr=False)["id"]})

    assert ineligible["payback_years"] > compliant["payback_years"]
    assert ineligible["lifetime_net_savings_inr"] < compliant["lifetime_net_savings_inr"]


def test_wattage_comes_from_the_catalog(client, project_payload, make_panel):
    panel = make_panel(wp=545)

    result = _calculate(client, {
        **project_payload, "panel_model_id": panel["id"], "panel_wattage": 999,
    })

    # The catalog is the source of truth once a model is chosen.
    assert result["panel_wattage"] == 545
    assert result["capacity_kwp"] == pytest.approx(project_payload["num_panels"] * 545 / 1000)


def test_projects_without_a_catalog_panel_are_untouched(client, project_payload):
    result = _calculate(client, project_payload)

    # Pre-catalog rows assert nothing and keep their subsidy.
    assert result["compliance_json"] is None
    assert result["subsidy_applied_inr"] == 78_000
    assert result["panel_wattage"] == project_payload["panel_wattage"]


def test_another_firms_panel_cannot_be_attached(client, other_org_client, project_payload, make_panel):
    panel = make_panel()

    # Org B references Org A's private panel; it is invisible, so nothing is asserted
    # from it and no subsidy is silently granted on its compliance.
    result = _calculate(other_org_client, {**project_payload, "panel_model_id": panel["id"]})
    assert result["compliance_json"] is None


# --- the proposal itself ---------------------------------------------------

def test_pdf_states_compliance_failures_and_the_lost_subsidy(client, project_payload, make_panel):
    panel = make_panel(dcr=False)
    project_id = client.post("/api/projects/", json={**project_payload, "panel_model_id": panel["id"]}).json()["id"]
    client.post(f"/api/projects/{project_id}/calculate")

    from tests.test_api import _pdf_text
    text = _pdf_text(client.get(f"/api/projects/{project_id}/report/pdf").content)

    assert "COMPLIANCE" in text
    assert "not DCR compliant" in text
    # The zero must read as ineligibility, not as a missing input.
    assert "Subsidy (not eligible, see Compliance)" in text


def test_pdf_of_a_compliant_project_shows_the_subsidy_normally(client, project_payload, make_panel):
    project_id = client.post("/api/projects/", json={
        **project_payload, "panel_model_id": make_panel()["id"],
    }).json()["id"]
    client.post(f"/api/projects/{project_id}/calculate")

    from tests.test_api import _pdf_text
    text = _pdf_text(client.get(f"/api/projects/{project_id}/report/pdf").content)

    assert "Subsidy (PM Surya Ghar)" in text
    assert "Rs. 78,000" in text
    assert "not eligible" not in text
