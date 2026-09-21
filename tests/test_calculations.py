import pytest
import json
from app.calculations.solar import (
    DEFAULT_IRRADIANCE_CALIBRATION,
    calculate_capacity_kwp,
    calculate_total_system_loss,
    calculate_performance_ratio,
    calculate_annual_generation_kwh,
    calculate_specific_yield,
    calculate_monthly_generation,
    calculate_lifetime_generation,
    perform_all_calculations
)
from app.services.irradiance import fallback_irradiance

# The reference proposal: 15 x 635 W at Gurugram, 21.5% total loss.
REFERENCE_PROJECT = {
    "num_panels": 15,
    "panel_wattage": 635,
    "degradation_rate": 0.7,
    "temp_loss_pct": 11.5,
    "shading_loss_pct": 0.0,
    "soiling_loss_pct": 3.0,
    "inverter_loss_pct": 3.0,
    "mismatch_loss_pct": 2.0,
    "dc_wiring_loss_pct": 2.0,
    "ac_wiring_loss_pct": 0.0,
    "irradiance_calibration": DEFAULT_IRRADIANCE_CALIBRATION,
}


def _flat_irradiance(h_annual):
    return {"monthly_h": [h_annual / 12] * 12, "h_annual": h_annual, "source": "pvgis"}


def test_capacity_calculation():
    # 15 panels * 635 W = 9525 W = 9.525 kWp
    assert calculate_capacity_kwp(15, 635) == 9.525

    with pytest.raises(ValueError):
        calculate_capacity_kwp(-1, 635)


def test_total_system_loss():
    # Sum of losses = 21.5%
    loss = calculate_total_system_loss(11.5, 0.0, 3.0, 3.0, 2.0, 2.0, 0.0)
    assert loss == 21.5


def test_performance_ratio():
    # PR = 100 - 21.5 = 78.5%
    assert calculate_performance_ratio(21.5) == 78.5


def test_annual_generation():
    # 9.525 kWp x 1000 kWh/m2 x 78.5% PR
    assert calculate_annual_generation_kwh(9.525, 78.5, 1000) == pytest.approx(7477.125)
    assert calculate_annual_generation_kwh(0, 78.5, 1000) == 0.0


def test_specific_yield():
    yield_val = calculate_specific_yield(13344.5, 9.525)
    assert yield_val == pytest.approx(1401.0, 0.1)


def test_monthly_generation_follows_irradiance(gurugram_irradiance):
    annual = 13344.5
    data = json.loads(calculate_monthly_generation(annual, gurugram_irradiance["monthly_h"]))

    assert len(data) == 12
    # Per-month rounding to 0.1 kWh can drift the total by at most 12 x 0.05.
    assert sum(d["value_kwh"] for d in data) == pytest.approx(annual, abs=0.6)
    assert data[5]["season"] == "Monsoon"  # June
    assert data[0]["season"] == "Regular"  # January
    # The monsoon dip now comes from the data: August well below April at Gurugram.
    assert data[7]["value_kwh"] < 0.7 * data[3]["value_kwh"]


def test_monthly_generation_rejects_bad_profile():
    with pytest.raises(ValueError):
        calculate_monthly_generation(1000, [1.0] * 11)
    with pytest.raises(ValueError):
        calculate_monthly_generation(1000, [0.0] * 12)


def test_lifetime_generation():
    # Using approx values from the report
    res = calculate_lifetime_generation(13344.5, 0.7, 25)
    # Report shows 303.5 MWh lifetime and 11.0 MWh in Year 25
    assert res['lifetime_mwh'] == pytest.approx(303.6, 0.5)
    assert res['final_year_mwh'] == pytest.approx(11.3, 0.5)


def test_reference_site_reproduces_reference_yield(gurugram_irradiance):
    # The calibration anchor: real PVGIS data for Gurugram must land on the
    # reference proposal's 1401 kWh/kWp.
    res = perform_all_calculations(REFERENCE_PROJECT, gurugram_irradiance)

    assert res["capacity_kwp"] == 9.525
    assert res["total_system_loss"] == 21.5
    assert res["performance_ratio"] == 78.5
    assert res["specific_yield"] == pytest.approx(1401, abs=0.5)
    assert res["annual_gen_kwh"] == pytest.approx(13344.5, rel=1e-3)
    assert res["irradiance_source"] == "pvgis"
    assert res["irradiance_h_annual"] == pytest.approx(2149.08)
    assert res["is_calculated"] is True


def test_generation_scales_with_site_irradiance():
    # The whole point of the phase: a sunnier site generates proportionally more.
    base = perform_all_calculations(REFERENCE_PROJECT, _flat_irradiance(2000))
    dimmer = perform_all_calculations(REFERENCE_PROJECT, _flat_irradiance(1800))

    assert dimmer["annual_gen_kwh"] / base["annual_gen_kwh"] == pytest.approx(0.9)


def test_calibration_scales_generation():
    raw = perform_all_calculations({**REFERENCE_PROJECT, "irradiance_calibration": 1.0}, _flat_irradiance(2000))
    calibrated = perform_all_calculations(REFERENCE_PROJECT, _flat_irradiance(2000))

    assert calibrated["annual_gen_kwh"] / raw["annual_gen_kwh"] == pytest.approx(DEFAULT_IRRADIANCE_CALIBRATION)


def test_fallback_reproduces_reference_yield():
    res = perform_all_calculations(REFERENCE_PROJECT, fallback_irradiance())

    assert res["specific_yield"] == pytest.approx(1401, abs=0.5)
    assert res["irradiance_source"] == "fallback"
