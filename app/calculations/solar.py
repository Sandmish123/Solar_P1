import json

# PVGIS uses ERA5 reanalysis for India, and ERA5 overestimates irradiance under heavy
# aerosol haze: raw PVGIS over-promises ~20% for Delhi NCR. This factor anchors the
# absolute level to the one known-good point, the reference proposal's 1401 kWh/kWp at
# Gurugram with PR 78.5%, against PVGIS v5_3 H(i)_y = 2149.08 kWh/m2 for that cell:
# (1401 / 0.785) / 2149.08. PVGIS still supplies everything site-relative.
# ponytail: one national factor. ERA5's haze bias is smaller in the south, so this
# under-promises there; switch to per-region factors once field data exists.
DEFAULT_IRRADIANCE_CALIBRATION = 0.8305

# Standard normal z for 90% exceedance: P90 is the yield beaten in nine years out of ten.
P90_Z_SCORE = 1.282

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# South-west monsoon, Jun-Sep. A chart label only: the generation dip itself comes
# from the irradiance data.
MONSOON_MONTHS = {5, 6, 7, 8}


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


def calculate_annual_generation_kwh(capacity_kwp: float, performance_ratio: float, h_annual: float) -> float:
    """
    First-year AC generation from in-plane irradiation (kWh/m2/yr).
    Modules are rated at 1 kW/m2, so each kWh/m2 of irradiation yields 1 kWh per kWp
    before losses; PR then applies the loss stack.
    """
    if capacity_kwp <= 0:
        return 0.0
    return capacity_kwp * h_annual * performance_ratio / 100.0


def calculate_p90_kwh(annual_gen_kwh: float, relative_sd: float):
    """Yield exceeded in nine years out of ten, from PVGIS's interannual standard
    deviation. None when the dataset gave no SD, e.g. the fallback profile.

    This is **weather variability only**. A bank's P90 also carries model and
    degradation uncertainty and will be lower; do not present this as bankable.
    """
    if relative_sd is None or relative_sd <= 0:
        return None
    return round(annual_gen_kwh * (1 - P90_Z_SCORE * relative_sd), 1)


def calculate_specific_yield(annual_gen_kwh: float, capacity_kwp: float) -> float:
    """Calculates specific yield (kWh / kWp)."""
    if capacity_kwp <= 0:
        return 0.0
    return round(annual_gen_kwh / capacity_kwp, 1)


def calculate_monthly_generation(annual_gen_kwh: float, monthly_h: list, monthly_shading_pct: list = None) -> str:
    """
    Distributes annual generation by each month's share of in-plane irradiation, less
    that month's shading. Without the shading argument a shaded December and an
    unshaded June split the year purely on sunlight, which understates the winter dip.

    The annual total is unchanged: shading is already in the loss stack via the
    performance ratio, so this only reshapes the year.

    Returns JSON string for storage in DB/Frontend.
    """
    if len(monthly_h) != 12:
        raise ValueError("monthly_h must be 12 values with a positive total")

    if monthly_shading_pct is None:
        available = list(monthly_h)
    else:
        if len(monthly_shading_pct) != 12:
            raise ValueError("monthly_shading_pct must be 12 values")
        available = [h * max(0.0, 1 - shaded / 100) for h, shaded in zip(monthly_h, monthly_shading_pct)]

    total = sum(available)
    if total <= 0:
        raise ValueError("monthly_h must be 12 values with a positive total")

    monthly_data = [
        {
            "month": MONTHS[i],
            "value_kwh": round(annual_gen_kwh * share / total, 1),
            "season": "Monsoon" if i in MONSOON_MONTHS else "Regular",
        }
        for i, share in enumerate(available)
    ]
    return json.dumps(monthly_data)


def generation_by_year(year1_generated_kwh: float, degradation_pct: float, num_years: int = 25) -> list:
    """Yearly generation with compounded degradation, year 1 first. Shared with the
    financial model so both use the same degradation curve."""
    retained = 1.0 - degradation_pct / 100.0
    return [year1_generated_kwh * retained ** year for year in range(num_years)]


def calculate_lifetime_generation(year1_generated_kwh: float, degradation_pct: float, num_years: int = 25) -> dict:
    """
    Calculates lifetime generation with compounded yearly degradation.
    """
    if num_years <= 0 or year1_generated_kwh <= 0:
        return {"lifetime_mwh": 0.0, "final_year_mwh": 0.0}

    yearly = generation_by_year(year1_generated_kwh, degradation_pct, num_years)
    return {
        "lifetime_mwh": round(sum(yearly) / 1000.0, 1),
        "final_year_mwh": round(yearly[-1] / 1000.0, 1)
    }


def perform_all_calculations(project_data: dict, irradiance: dict, shading: dict = None) -> dict:
    """
    Runs all calculations and returns a dict of results.
    `irradiance` is {"monthly_h": [12 x kWh/m2], "h_annual": kWh/m2/yr, "source": str,
    "relative_sd": float|None}, as returned by app.services.irradiance.get_irradiance.
    `shading` is the dict from app.calculations.shading.compute_shading, or None.
    """
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

    # 4. Annual Generation, from dataset irradiance corrected for its absolute bias
    effective_h = irradiance['h_annual'] * project_data['irradiance_calibration']
    annual_kwh = calculate_annual_generation_kwh(cap_kwp, pr, effective_h)

    # 5. Specific Yield
    spec_yield = calculate_specific_yield(annual_kwh, cap_kwp)

    # 6. Monthly Generation, reshaped by each month's shading where it is known
    monthly_json = calculate_monthly_generation(
        annual_kwh, irradiance['monthly_h'], shading['monthly_pct'] if shading else None
    )

    # 7. Lifetime Generation (25 yrs)
    lifetime_data = calculate_lifetime_generation(annual_kwh, project_data.get('degradation_rate', 0.7))

    return {
        "capacity_kwp": cap_kwp,
        "total_system_loss": total_loss,
        "performance_ratio": pr,
        "annual_gen_kwh": annual_kwh,
        "specific_yield": spec_yield,
        "annual_gen_p90_kwh": calculate_p90_kwh(annual_kwh, irradiance.get('relative_sd')),
        "lifetime_gen_mwh": lifetime_data['lifetime_mwh'],
        "year25_output_mwh": lifetime_data['final_year_mwh'],
        "monthly_gen_json": monthly_json,
        "irradiance_source": irradiance['source'],
        "irradiance_h_annual": irradiance['h_annual'],
        "is_calculated": True
    }
