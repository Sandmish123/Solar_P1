import json

# Standard peak sun hours for Northern India region (e.g. Gurugram)
# This acts as a base multiplier for specific yield
APPROX_PEAK_SUN_HOURS = 1400  # Adjust slightly to match the report's 1401

def calculate_capacity_kwp(num_panels: int, panel_wattage_w: float) -> float:
    """Calculates system capacity in kWp."""
    if num_panels < 0 or panel_wattage_w < 0:
        raise ValueError("Panels and wattage must be positive")
    return (num_panels * panel_wattage_w) / 1000.0


def calculate_total_system_loss(
    temp_loss: float, shading_loss: float, soiling_loss: float,
    inverter_loss: float, mismatch_loss: float, dc_wiring_loss: float,
    ac_wiring_loss: float
) -> float:
    """Calculates total system loss using additive approach to match the Reslink PDF."""
    total = sum([
        float(temp_loss), float(shading_loss), float(soiling_loss),
        float(inverter_loss), float(mismatch_loss), float(dc_wiring_loss),
        float(ac_wiring_loss)
    ])
    return min(total, 100.0)


def calculate_performance_ratio(total_loss_pct: float) -> float:
    """Calculates PR based on total system loss."""
    if total_loss_pct >= 100.0:
        return 0.0
    return 100.0 - total_loss_pct


def calculate_annual_generation_kwh(capacity_kwp: float, performance_ratio: float, location_yield_factor: float = 1401) -> float:
    """
    Calculates 1st year annual generation.
    Uses a standard location_yield_factor (simulated base peak sun hours).
    In a real app, this would query a solar API by coordinates (e.g., PVGIS).
    Here we match the PDF math: 9.53 * 1401 = 13351, performance ratio is already baked into specific yield in PDF presentation,
    Wait, PDF says: Specific yield = 1401, Annual = 13.3 MWh (13,344 kWh). 9.525 * 1401 = 13344.525.
    So Annual = capacity * specific_yield directly.
    """
    if capacity_kwp <= 0:
        return 0.0
    return capacity_kwp * location_yield_factor


def calculate_specific_yield(annual_gen_kwh: float, capacity_kwp: float) -> float:
    """Calculates specific yield (kWh / kWp)."""
    if capacity_kwp <= 0:
        return 0.0
    return round(annual_gen_kwh / capacity_kwp, 1)


def calculate_monthly_generation(annual_gen_kwh: float) -> str:
    """
    Distributes annual generation into months.
    Returns JSON string for storage in DB/Frontend.
    """
    # Standard distribution for India (~28°N)
    factors = [
        0.075,  # Jan
        0.080,  # Feb
        0.095,  # Mar
        0.100,  # Apr
        0.105,  # May
        0.085,  # Jun (Monsoon)
        0.070,  # Jul (Monsoon)
        0.070,  # Aug (Monsoon)
        0.075,  # Sep (Monsoon)
        0.085,  # Oct
        0.080,  # Nov
        0.080   # Dec
    ]
    
    # Normalize to ensure exactly 1.0 sum due to float math
    total = sum(factors)
    normalized = [f / total for f in factors]
    
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    monthly_data = []
    
    for i, factor in enumerate(normalized):
        val = annual_gen_kwh * factor
        # Label monsoon months
        is_monsoon = 5 <= i <= 8  # Jun(5) to Sep(8)
        monthly_data.append({
            "month": months[i],
            "value_kwh": round(val, 1),
            "season": "Monsoon" if is_monsoon else "Regular"
        })
        
    return json.dumps(monthly_data)


def calculate_lifetime_generation(year1_generated_kwh: float, degradation_pct: float, num_years: int = 25) -> dict:
    """
    Calculates lifetime generation with compounded yearly degradation.
    """
    if num_years <= 0 or year1_generated_kwh <= 0:
        return {"lifetime_mwh": 0.0, "final_year_mwh": 0.0}
        
    deg_rate = degradation_pct / 100.0
    total_kwh = year1_generated_kwh
    current_year_kwh = year1_generated_kwh
    
    for _ in range(1, num_years):
        current_year_kwh = current_year_kwh * (1.0 - deg_rate)
        total_kwh += current_year_kwh
        
    return {
        "lifetime_mwh": round(total_kwh / 1000.0, 1),
        "final_year_mwh": round(current_year_kwh / 1000.0, 1)
    }


def perform_all_calculations(project_data: dict) -> dict:
    """Runs all calculations and returns a dict of results."""
    # 1. Capacity
    cap_kwp = calculate_capacity_kwp(project_data['num_panels'], project_data['panel_wattage'])
    
    # 2. Losses
    total_loss = calculate_total_system_loss(
        project_data['temp_loss_pct'], project_data['shading_loss_pct'],
        project_data['soiling_loss_pct'], project_data['inverter_loss_pct'],
        project_data['mismatch_loss_pct'], project_data['dc_wiring_loss_pct'],
        project_data['ac_wiring_loss_pct']
    )
    
    # 3. Performance Ratio
    pr = calculate_performance_ratio(total_loss)
    
    # 4. Annual Generation (Uses static multiplier for simplicity, real app might integrate PR)
    # The reference PDF implies specific yield = 1401 and Annual Gen = Capacity * Specific Yield
    specific_yield_base = 1401.0
    # Add slight variation based on PR (if PR is higher, yield is higher)
    adjusted_yield = specific_yield_base * (pr / 78.5) # Normalized to reference 78.5%
    
    annual_kwh = calculate_annual_generation_kwh(cap_kwp, pr, adjusted_yield)
    
    # 5. Specific Yield
    spec_yield = calculate_specific_yield(annual_kwh, cap_kwp)
    
    # 6. Monthly Generation
    monthly_json = calculate_monthly_generation(annual_kwh)
    
    # 7. Lifetime Generation (25 yrs)
    lifetime_data = calculate_lifetime_generation(annual_kwh, project_data.get('degradation_rate', 0.7))
    
    return {
        "capacity_kwp": cap_kwp,
        "total_system_loss": total_loss,
        "performance_ratio": pr,
        "annual_gen_kwh": annual_kwh,
        "specific_yield": spec_yield,
        "lifetime_gen_mwh": lifetime_data['lifetime_mwh'],
        "year25_output_mwh": lifetime_data['final_year_mwh'],
        "monthly_gen_json": monthly_json,
        "is_calculated": True
    }
