import json

import pytest

from app.calculations.financial import (
    FINANCIAL_RESULT_FIELDS,
    GRID_EMISSION_FACTOR_KG_PER_KWH,
    build_cashflow,
    calculate_pm_surya_ghar_subsidy,
    irr,
    npv,
    payback_years,
    perform_financial_calculations,
)
from app.calculations.solar import generation_by_year

# The reference 9.525 kWp Gurugram system at Rs. 55,000/kWp, first-year
# generation from the calibrated PVGIS model.
CAPACITY_KWP = 9.525
YEAR1_KWH = 13345.3
REFERENCE_INPUTS = {
    "system_cost_inr": 55_000 * CAPACITY_KWP,
    "subsidy_inr": None,
    "tariff_inr_per_kwh": 8.0,
    "tariff_escalation_pct": 3.0,
    "export_ratio_pct": 30.0,
    "export_tariff_inr_per_kwh": 3.0,
    "om_cost_pct": 1.0,
    "discount_rate_pct": 8.0,
}


def _run(**overrides):
    return perform_financial_calculations({**REFERENCE_INPUTS, **overrides}, CAPACITY_KWP, YEAR1_KWH, 0.7)


# --- subsidy ---------------------------------------------------------------

@pytest.mark.parametrize("capacity_kw, expected", [
    (0, 0),
    (0.5, 15_000),
    (1, 30_000),
    (2, 60_000),
    (2.5, 69_000),    # 60,000 + 0.5 x 18,000
    (3, 78_000),
    (9.525, 78_000),  # capped
])
def test_pm_surya_ghar_slabs(capacity_kw, expected):
    assert calculate_pm_surya_ghar_subsidy(capacity_kw) == pytest.approx(expected)


# --- building blocks -------------------------------------------------------

def test_cashflow_rows_by_hand():
    rows = build_cashflow([1000, 990], 8.0, 5.0, 30.0, 3.0, 100.0)

    # Year 1: 700 kWh self-used at Rs. 8, 300 kWh exported at Rs. 3.
    assert rows[0]["savings_inr"] == pytest.approx(700 * 8 + 300 * 3)
    assert rows[0]["net_inr"] == pytest.approx(6400)
    # Year 2: grid tariff escalates to 8.40; export tariff and O&M stay flat.
    assert rows[1]["grid_tariff_inr"] == pytest.approx(8.4)
    assert rows[1]["savings_inr"] == pytest.approx(693 * 8.4 + 297 * 3)
    assert rows[1]["om_inr"] == 100.0


def test_payback_interpolates_within_the_year():
    assert payback_years(100, [30] * 5) == pytest.approx(10 / 3)
    # A negative first year pushes recovery out: 110 left after year 1.
    assert payback_years(100, [-10, 60, 60]) == pytest.approx(2 + 50 / 60)


def test_payback_edges():
    assert payback_years(100, [10] * 5) is None
    assert payback_years(0, [10] * 5) == 0.0


def test_irr_known_values():
    assert irr([-100, 110]) == pytest.approx(0.10)
    # 60x + 60x^2 = 100 with x = 1/(1+r)  ->  r = 13.066%
    assert irr([-100, 60, 60]) == pytest.approx(0.130662, rel=1e-5)


def test_irr_is_a_root_of_npv():
    flows = [-445_875] + [80_000 * 1.02 ** year for year in range(25)]
    assert npv(irr(flows), flows) == pytest.approx(0, abs=1e-3)


def test_irr_undefined_without_a_sign_change():
    assert irr([100, 10]) is None
    assert irr([0, 10, 10]) is None


def test_npv():
    assert npv(0.10, [-100, 110]) == pytest.approx(0)
    assert npv(0.0, [-100, 30, 30]) == pytest.approx(-40)


# --- full model ------------------------------------------------------------

def test_reference_system():
    res = _run()

    assert res["subsidy_applied_inr"] == 78_000
    assert res["net_investment_inr"] == round(55_000 * CAPACITY_KWP - 78_000)
    assert res["year1_savings_inr"] == round(YEAR1_KWH * 0.7 * 8 + YEAR1_KWH * 0.3 * 3)
    # The plan's sanity band for this system; outside it means a sign error.
    assert 4 <= res["payback_years"] <= 6
    # Pinned, like the 1401 kWh/kWp anchor: if these move, the model changed.
    assert res["payback_years"] == 5.2
    assert res["irr_pct"] == 20.0
    assert res["discounted_payback_years"] > res["payback_years"]


def test_cashflow_is_consistent_with_headline_numbers():
    res = _run()
    rows = json.loads(res["cashflow_json"])

    assert [r["year"] for r in rows] == list(range(1, 26))
    # Stored rows are rounded per year, so allow a rupee per row of drift.
    assert rows[-1]["cumulative_inr"] == pytest.approx(res["lifetime_net_savings_inr"], abs=25)
    assert rows[0]["cumulative_inr"] == pytest.approx(-res["net_investment_inr"] + rows[0]["net_inr"], abs=1)


def test_co2_uses_cea_factor_and_degradation():
    expected = sum(generation_by_year(YEAR1_KWH, 0.7, 25)) * GRID_EMISSION_FACTOR_KG_PER_KWH / 1000
    assert _run()["co2_offset_tonnes"] == pytest.approx(expected, abs=0.05)


def test_lcoe_undiscounted_without_om_is_cost_over_energy():
    res = _run(discount_rate_pct=0.0, om_cost_pct=0.0)
    lifetime_kwh = sum(generation_by_year(YEAR1_KWH, 0.7, 25))
    assert res["lcoe_inr_per_kwh"] == pytest.approx(res["net_investment_inr"] / lifetime_kwh, abs=0.01)


def test_no_system_cost_means_no_financials():
    res = _run(system_cost_inr=None)
    assert set(res) == set(FINANCIAL_RESULT_FIELDS)
    assert all(value is None for value in res.values())


def test_subsidy_override_replaces_auto_calculation():
    # 0 is how an operator marks a commercial, non-eligible system.
    res = _run(subsidy_inr=0)
    assert res["subsidy_applied_inr"] == 0
    assert res["net_investment_inr"] == round(REFERENCE_INPUTS["system_cost_inr"])


def test_subsidy_above_cost_is_clamped():
    res = _run(system_cost_inr=50_000, subsidy_inr=78_000)
    assert res["subsidy_applied_inr"] == 50_000
    assert res["net_investment_inr"] == 0
    assert res["payback_years"] == 0.0
    assert res["irr_pct"] is None


def test_uneconomic_system_never_pays_back():
    res = _run(tariff_inr_per_kwh=0.5, export_tariff_inr_per_kwh=0.0)
    assert res["payback_years"] is None
    assert res["lifetime_net_savings_inr"] < 0
