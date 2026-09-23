"""Customer financials for a rooftop system: subsidy, 25-year cashflow, payback, IRR.

Pure functions, no DB or I/O, mirroring app/calculations/solar.py. Amounts are INR.
ponytail: floats, rounded to whole rupees only for storage. These are projections, not
a ledger; move to Decimal if this ever books real money.
"""
import json

from app.calculations.solar import generation_by_year

# PM Surya Ghar: Muft Bijli Yojana central financial assistance, residential rooftop,
# as marginal bands of (band upper bound in kW, INR per kW within the band). Nothing is
# paid above 3 kW, so the total caps at 78,000. Checked against 2026 scheme guides.
# Rates get revised, which is why subsidy_inr is operator-overridable; it is also the
# only way to express non-residential (0) or special-category-state rates.
PM_SURYA_GHAR_SLABS = [(2.0, 30_000), (3.0, 18_000)]

# CEA CO2 Baseline Database v21.0 (Dec 2025), Table S: all-India weighted average for
# FY 2024-25. Lower than the combined margin (0.736), so the conservative offset claim.
GRID_EMISSION_FACTOR_KG_PER_KWH = 0.710

PROJECTION_YEARS = 25

# String inverters are usually replaced once in a 25-year system life. Leaving that
# cost out makes the lifetime savings look better than they will be, so it is modelled
# by default rather than opted into. Typical Indian rooftop inverter cost is around a
# tenth of the installed price; the operator can override the amount, or set the year
# to 0 for a system where it does not apply.
INVERTER_COST_SHARE = 0.12
DEFAULT_INVERTER_REPLACEMENT_YEAR = 12

FINANCIAL_RESULT_FIELDS = (
    "subsidy_applied_inr",
    "net_investment_inr",
    "year1_savings_inr",
    "payback_years",
    "discounted_payback_years",
    "irr_pct",
    "npv_inr",
    "lifetime_net_savings_inr",
    "lcoe_inr_per_kwh",
    "co2_offset_tonnes",
    "inverter_replacement_applied_inr",
    "cashflow_json",
)


def calculate_pm_surya_ghar_subsidy(capacity_kw: float) -> float:
    """Central subsidy for a residential system, pro-rata within each band."""
    subsidy, band_start = 0.0, 0.0
    for band_end, inr_per_kw in PM_SURYA_GHAR_SLABS:
        if capacity_kw <= band_start:
            break
        subsidy += (min(capacity_kw, band_end) - band_start) * inr_per_kw
        band_start = band_end
    return subsidy


def build_cashflow(
    generation_kwh: list,
    tariff_inr_per_kwh: float,
    tariff_escalation_pct: float,
    export_ratio_pct: float,
    export_tariff_inr_per_kwh: float,
    om_cost_inr: float,
    replacement_year: int = 0,
    replacement_cost_inr: float = 0.0,
) -> list:
    """
    One row per year. Self-consumed units are valued at the grid tariff, which escalates;
    the exported surplus is paid at the export tariff, held flat (regulated APPC-linked
    rates). O&M is held flat too, as is the inverter replacement, which lands once in
    `replacement_year` (1-based; 0 disables it).
    """
    rows = []
    for index, generated in enumerate(generation_kwh):
        year = index + 1
        grid_tariff = tariff_inr_per_kwh * (1 + tariff_escalation_pct / 100) ** index
        exported = generated * export_ratio_pct / 100
        savings = (generated - exported) * grid_tariff + exported * export_tariff_inr_per_kwh
        replacement = replacement_cost_inr if year == replacement_year else 0.0
        rows.append({
            "year": year,
            "generation_kwh": generated,
            "grid_tariff_inr": grid_tariff,
            "savings_inr": savings,
            "om_inr": om_cost_inr,
            "replacement_inr": replacement,
            "net_inr": savings - om_cost_inr - replacement,
        })
    return rows


def payback_years(investment: float, yearly_net: list):
    """Years until cumulative net cashflow recovers the investment, interpolated within
    the payback year. None if it never does within the horizon."""
    if investment <= 0:
        return 0.0
    remaining = investment
    for year, net in enumerate(yearly_net, start=1):
        if net >= remaining:
            return year - 1 + remaining / net
        remaining -= net
    return None


def npv(rate: float, cashflows: list) -> float:
    """Net present value; cashflows[0] is at t=0."""
    return sum(cashflow / (1 + rate) ** t for t, cashflow in enumerate(cashflows))


def irr(cashflows: list, low: float = -0.99, high: float = 10.0, iterations: int = 200):
    """
    Internal rate of return by bisection. None if NPV doesn't change sign on
    [low, high], e.g. zero investment. Heavily subsidised small systems can exceed
    100%, hence the wide upper bound.
    ponytail: assumes one sign change (outlay, then inflows). A replacement year big
    enough to turn that year negative could admit a second root; bisection returns one
    of them.
    """
    npv_low = npv(low, cashflows)
    if npv_low * npv(high, cashflows) > 0:
        return None
    for _ in range(iterations):
        mid = (low + high) / 2
        npv_mid = npv(mid, cashflows)
        if npv_low * npv_mid <= 0:
            high = mid
        else:
            low, npv_low = mid, npv_mid
        if high - low < 1e-12:
            break
    return (low + high) / 2


def _round_or_none(value, digits):
    return None if value is None else round(value, digits)


def perform_financial_calculations(inputs: dict, capacity_kwp: float, year1_kwh: float, degradation_pct: float) -> dict:
    """
    Runs the financial model and returns a dict of results keyed by
    FINANCIAL_RESULT_FIELDS. All None when system_cost_inr is absent: an invented cost
    in a customer proposal is worse than a missing section.
    """
    cost = inputs["system_cost_inr"]
    if cost is None:
        return dict.fromkeys(FINANCIAL_RESULT_FIELDS)

    subsidy = inputs["subsidy_inr"]
    if subsidy is None:
        subsidy = calculate_pm_surya_ghar_subsidy(capacity_kwp)
    subsidy = min(subsidy, cost)
    investment = cost - subsidy

    replacement_year = int(inputs.get("inverter_replacement_year") or 0)
    replacement_cost = inputs.get("inverter_replacement_cost_inr")
    if replacement_cost is None:
        replacement_cost = cost * INVERTER_COST_SHARE
    if not 1 <= replacement_year <= PROJECTION_YEARS or replacement_cost <= 0:
        replacement_year, replacement_cost = 0, 0.0

    generation = generation_by_year(year1_kwh, degradation_pct, PROJECTION_YEARS)
    rows = build_cashflow(
        generation,
        inputs["tariff_inr_per_kwh"],
        inputs["tariff_escalation_pct"],
        inputs["export_ratio_pct"],
        inputs["export_tariff_inr_per_kwh"],
        cost * inputs["om_cost_pct"] / 100,
        replacement_year,
        replacement_cost,
    )

    nets = [row["net_inr"] for row in rows]
    rate = inputs["discount_rate_pct"] / 100
    discount = [(1 + rate) ** year for year in range(1, PROJECTION_YEARS + 1)]
    return_rate = irr([-investment] + nets)

    # Customer's cost per kWh over the system life: their outlay plus O&M and the
    # inverter replacement, over generation, all discounted.
    lcoe = (
        investment
        + sum((row["om_inr"] + row["replacement_inr"]) / d for row, d in zip(rows, discount))
    ) / sum(g / d for g, d in zip(generation, discount))

    cumulative = -investment
    stored_rows = []
    for row in rows:
        cumulative += row["net_inr"]
        stored_rows.append({
            "year": row["year"],
            "generation_kwh": round(row["generation_kwh"], 1),
            "grid_tariff_inr": round(row["grid_tariff_inr"], 2),
            "savings_inr": round(row["savings_inr"]),
            "om_inr": round(row["om_inr"]),
            "replacement_inr": round(row["replacement_inr"]),
            "net_inr": round(row["net_inr"]),
            "cumulative_inr": round(cumulative),
        })

    return {
        "subsidy_applied_inr": round(subsidy),
        "net_investment_inr": round(investment),
        "year1_savings_inr": round(rows[0]["savings_inr"]),
        "payback_years": _round_or_none(payback_years(investment, nets), 1),
        "discounted_payback_years": _round_or_none(
            payback_years(investment, [n / d for n, d in zip(nets, discount)]), 1
        ),
        "irr_pct": _round_or_none(None if return_rate is None else return_rate * 100, 1),
        "npv_inr": round(npv(rate, [-investment] + nets)),
        "lifetime_net_savings_inr": round(sum(nets) - investment),
        "lcoe_inr_per_kwh": round(lcoe, 2),
        "co2_offset_tonnes": round(sum(generation) * GRID_EMISSION_FACTOR_KG_PER_KWH / 1000, 1),
        "inverter_replacement_applied_inr": round(replacement_cost) if replacement_year else None,
        "cashflow_json": json.dumps(stored_rows),
    }
