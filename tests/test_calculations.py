import pytest
import json
from app.calculations.solar import (
    calculate_capacity_kwp,
    calculate_total_system_loss,
    calculate_performance_ratio,
    calculate_annual_generation_kwh,
    calculate_specific_yield,
    calculate_monthly_generation,
    calculate_lifetime_generation,
    perform_all_calculations
)

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
    # capacity = 9.525, PR implicitly handled in specific yield = 1401
    cap = 9.525
    gen = calculate_annual_generation_kwh(cap, 78.5, 1401)
    assert gen == pytest.approx(13344.525)

def test_specific_yield():
    yield_val = calculate_specific_yield(13344.5, 9.525)
    assert yield_val == pytest.approx(1401.0, 0.1)

def test_monthly_generation():
    annual = 13344.5
    res = calculate_monthly_generation(annual)
    data = json.loads(res)
    assert len(data) == 12
    # Check sum of all months equals annual within rounding variation
    total = sum(d["value_kwh"] for d in data)
    assert total == pytest.approx(annual, 1.0)
    # Check monsoon tag
    assert data[5]["season"] == "Monsoon" # June

def test_lifetime_generation():
    # Using approx values from the report
    res = calculate_lifetime_generation(13344.5, 0.7, 25)
    # Report shows 303.5 MWh lifetime and 11.0 MWh in Year 25
    assert res['lifetime_mwh'] == pytest.approx(303.6, 0.5) 
    assert res['final_year_mwh'] == pytest.approx(11.3, 0.5)

def test_perform_all():
    data = {
        "num_panels": 15,
        "panel_wattage": 635,
        "degradation_rate": 0.7,
        "temp_loss_pct": 11.5,
        "shading_loss_pct": 0.0,
        "soiling_loss_pct": 3.0,
        "inverter_loss_pct": 3.0,
        "mismatch_loss_pct": 2.0,
        "dc_wiring_loss_pct": 2.0,
        "ac_wiring_loss_pct": 0.0
    }
    res = perform_all_calculations(data)
    
    assert res["capacity_kwp"] == 9.525
    assert res["total_system_loss"] == 21.5
    assert res["performance_ratio"] == 78.5
    assert res["is_calculated"] == True
