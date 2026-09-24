import json
from uuid import uuid4

import pytest

# A telescopic domestic tariff, invented for the tests only. No rates ship with the app.
TEST_SLABS = [
    {"upto": 100, "rate": 3.0},
    {"upto": 300, "rate": 6.0},
    {"upto": None, "rate": 9.0},
]


@pytest.fixture
def tariff_plan(client):
    def _make(slabs=None, **overrides):
        payload = {
            # Unique per call: (org_id, name) is unique and the test DB is shared.
            "name": f"Test DISCOM {uuid4().hex[:8]}",
            "discom": "TestPower",
            "category": "Domestic",
            "slabs_json": json.dumps(slabs or TEST_SLABS),
        }
        payload.update(overrides)
        response = client.post("/api/catalog/tariffs", json=payload)
        assert response.status_code == 201, response.text
        return response.json()
    return _make


def consumption(monthly_units, bill=None):
    return json.dumps([{"units": u, "bill_inr": bill} for u in monthly_units])


def calculate(client, payload):
    project_id = client.post("/api/projects/", json=payload).json()["id"]
    response = client.post(f"/api/projects/{project_id}/calculate")
    assert response.status_code == 200, response.text
    return response.json()


# --- tariff plans ----------------------------------------------------------

def test_a_tariff_plan_round_trips(client, tariff_plan):
    plan = tariff_plan()
    listed = client.get("/api/catalog/tariffs").json()

    assert any(p["id"] == plan["id"] for p in listed)
    assert json.loads(plan["slabs_json"])[0]["rate"] == 3.0


@pytest.mark.parametrize("slabs, reason", [
    ([{"upto": 100, "rate": 3.0}], "open-ended"),
    ([{"upto": 300, "rate": 3.0}, {"upto": 100, "rate": 6.0}], "increase"),
    ([{"upto": None, "rate": -1}], "negative"),
    ([], "at least one"),
])
def test_a_malformed_tariff_is_rejected(client, slabs, reason):
    # Rejected at the boundary: a bad tariff would misprice every saving built on it.
    response = client.post("/api/catalog/tariffs", json={
        "name": "Broken", "slabs_json": json.dumps(slabs),
    })
    assert response.status_code == 422


def test_tariff_plans_are_private_to_a_firm(client, other_org_client, tariff_plan):
    plan = tariff_plan()
    assert plan["id"] not in [p["id"] for p in other_org_client.get("/api/catalog/tariffs").json()]


# --- savings from real consumption -----------------------------------------

def test_without_consumption_the_flat_estimate_still_applies(client, project_payload):
    result = calculate(client, project_payload)

    assert result["savings_basis"] == "flat"
    # The old guessed split: 30% exported.
    assert result["exported_kwh"] == pytest.approx(result["annual_gen_kwh"] * 0.30, rel=1e-3)


def test_consumption_without_a_tariff_plan_falls_back(client, project_payload):
    # Consumption alone cannot be priced, so the estimate is unchanged.
    result = calculate(client, {**project_payload, "consumption_json": consumption([800] * 12)})
    assert result["savings_basis"] == "flat"


def test_consumption_and_a_tariff_switch_the_basis(client, project_payload, tariff_plan):
    plan = tariff_plan()

    result = calculate(client, {
        **project_payload,
        "consumption_json": consumption([900] * 12),
        "tariff_plan_id": plan["id"],
    })

    assert result["savings_basis"] == "consumption"
    # Generation is conserved across the settlement.
    assert result["self_consumed_kwh"] + result["exported_kwh"] == pytest.approx(
        result["annual_gen_kwh"], rel=1e-3
    )


def test_a_heavy_user_exports_nothing(client, project_payload, tariff_plan):
    plan = tariff_plan()

    result = calculate(client, {
        **project_payload,
        "consumption_json": consumption([3000] * 12),   # far beyond generation
        "tariff_plan_id": plan["id"],
    })

    assert result["exported_kwh"] == 0
    assert result["self_consumed_kwh"] == pytest.approx(result["annual_gen_kwh"], rel=1e-3)
    # Every unit displaces a top-slab unit, so it is worth the top rate.
    assert result["effective_rate_inr_per_kwh"] == pytest.approx(9.0, abs=0.2)


def test_a_light_user_exports_most_of_it(client, project_payload, tariff_plan):
    plan = tariff_plan()

    result = calculate(client, {
        **project_payload,
        "consumption_json": consumption([50] * 12),
        "tariff_plan_id": plan["id"],
    })

    assert result["exported_kwh"] > result["self_consumed_kwh"]
    # Exported units earn the low export rate, so each generated unit is worth far less.
    assert result["effective_rate_inr_per_kwh"] < 4.0


def test_banking_carries_earlier_surplus_into_a_later_month(client, project_payload, tariff_plan):
    plan = tariff_plan()
    # The whole year's load lands in November, long after the sunniest months.
    november_only = [0] * 10 + [6000, 0]

    result = calculate(client, {
        **project_payload,
        "consumption_json": consumption(november_only),
        "tariff_plan_id": plan["id"],
    })

    # November generates only ~1,100 units, so without banking most of those 6,000
    # would be bought at retail and the summer surplus sold at the low export rate.
    # Credit carried forward covers all of it.
    assert result["self_consumed_kwh"] == pytest.approx(6000, rel=0.01)
    assert result["exported_kwh"] == pytest.approx(result["annual_gen_kwh"] - 6000, rel=0.01)


def test_a_heavier_user_saves_more_per_unit(client, project_payload, tariff_plan):
    plan = tariff_plan()
    light = calculate(client, {**project_payload, "tariff_plan_id": plan["id"],
                               "consumption_json": consumption([100] * 12)})
    heavy = calculate(client, {**project_payload, "tariff_plan_id": plan["id"],
                               "consumption_json": consumption([2000] * 12)})

    assert heavy["effective_rate_inr_per_kwh"] > light["effective_rate_inr_per_kwh"]
    assert heavy["payback_years"] < light["payback_years"]


# --- consumption validation ------------------------------------------------

@pytest.mark.parametrize("bad", [
    json.dumps([{"units": 100}] * 11),                       # short year
    json.dumps([{"units": -5}] * 12),                        # negative units
    json.dumps([{"units": 100, "bill_inr": -1}] * 12),       # negative bill
    json.dumps({"units": 100}),                              # not a list
    "not json at all",
])
def test_bad_consumption_is_rejected(client, project_payload, bad):
    assert client.post("/api/projects/", json={
        **project_payload, "consumption_json": bad,
    }).status_code == 422


def test_all_zero_consumption_is_treated_as_not_supplied(client, project_payload, tariff_plan):
    plan = tariff_plan()
    result = calculate(client, {
        **project_payload, "tariff_plan_id": plan["id"],
        "consumption_json": consumption([0] * 12),
    })
    assert result["savings_basis"] == "flat"


# --- the bill cross-check --------------------------------------------------

def test_the_modelled_bill_is_compared_with_the_real_one(client, project_payload, tariff_plan):
    plan = tariff_plan()
    # 500 units: 100x3 + 200x6 + 200x9 = 3300 a month, 39,600 a year.
    result = calculate(client, {
        **project_payload, "tariff_plan_id": plan["id"],
        "consumption_json": consumption([500] * 12, bill=3300),
    })

    check = json.loads(result["tariff_check_json"])
    assert check["modelled_annual_bill_inr"] == pytest.approx(39_600, abs=50)
    assert abs(check["deviation_pct"]) < 1


def test_a_wrong_tariff_plan_shows_up_as_a_large_deviation(client, project_payload, tariff_plan):
    plan = tariff_plan()
    result = calculate(client, {
        **project_payload, "tariff_plan_id": plan["id"],
        "consumption_json": consumption([500] * 12, bill=1000),   # real bill far lower
    })

    check = json.loads(result["tariff_check_json"])
    assert check["deviation_pct"] > 100


# --- sizing ----------------------------------------------------------------

def test_sizing_is_limited_by_consumption_for_a_modest_user(client, project_payload, tariff_plan):
    plan = tariff_plan()
    result = calculate(client, {
        **project_payload, "tariff_plan_id": plan["id"],
        "consumption_json": consumption([500] * 12),    # 6,000 units a year
    })

    sizing = json.loads(result["sizing_json"])
    assert sizing["limited_by"] == "consumption"
    # 6,000 units at ~1400 kWh/kWp is a little over 4 kWp.
    assert result["recommended_kwp"] == pytest.approx(6000 / result["specific_yield"], rel=0.02)
    # The design is larger than needed, which the report can now say.
    assert result["recommended_kwp"] < result["capacity_kwp"]


def test_sizing_is_limited_by_budget_when_money_is_tight(client, project_payload, tariff_plan):
    plan = tariff_plan()
    result = calculate(client, {
        **project_payload, "tariff_plan_id": plan["id"],
        "consumption_json": consumption([3000] * 12),
        "budget_inr": 200_000,
    })

    sizing = json.loads(result["sizing_json"])
    assert sizing["limited_by"] == "budget"
    assert "roof" in sizing["ceilings_kwp"] and "consumption" in sizing["ceilings_kwp"]


def test_sizing_falls_back_to_the_roof_without_consumption(client, project_payload):
    result = calculate(client, project_payload)

    sizing = json.loads(result["sizing_json"])
    assert sizing["limited_by"] == "roof"
    assert "consumption" not in sizing["ceilings_kwp"]


# --- the proposal itself ---------------------------------------------------

def test_pdf_states_the_consumption_basis(client, project_payload, tariff_plan):
    plan = tariff_plan()
    project_id = client.post("/api/projects/", json={
        **project_payload, "tariff_plan_id": plan["id"],
        "consumption_json": consumption([900] * 12, bill=6000),
    }).json()["id"]
    client.post(f"/api/projects/{project_id}/calculate")

    from tests.test_api import _pdf_text
    text = _pdf_text(client.get(f"/api/projects/{project_id}/report/pdf").content)

    assert "Self-consumed / Exported" in text
    assert "own 12-month" in text
    assert "surplus banked" in text
    # The guessed export split must not be claimed when real bills were used.
    assert "assumed exported" not in text


def test_pdf_keeps_the_flat_wording_without_consumption(client, project_payload):
    project_id = _calculated(client, project_payload)

    from tests.test_api import _pdf_text
    text = _pdf_text(client.get(f"/api/projects/{project_id}/report/pdf").content)

    assert "assumed exported" in text
    assert "Self-consumed / Exported" not in text


def _calculated(client, payload):
    project_id = client.post("/api/projects/", json=payload).json()["id"]
    client.post(f"/api/projects/{project_id}/calculate")
    return project_id


def test_pdf_cashflow_shows_what_a_unit_is_worth(client, project_payload, tariff_plan):
    plan = tariff_plan()
    project_id = _calculated(client, {
        **project_payload, "tariff_plan_id": plan["id"],
        "consumption_json": consumption([2000] * 12),
    })

    from tests.test_api import _pdf_text
    text = _pdf_text(client.get(f"/api/projects/{project_id}/report/pdf").content)

    # Under a slab tariff with banking there is no single retail rate to quote.
    assert "Value/kWh" in text
    assert "Grid Tariff" not in text
