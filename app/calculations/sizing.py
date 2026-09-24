"""What capacity does this customer actually need?

Pure functions, no DB or IO. Answers the question customers ask before any other, and
which the app could not answer while system size was only an input.

Three ceilings, and the smallest wins:

- **Consumption**: enough to offset the year's units. Sizing past this banks surplus
  that settles at the low export rate, so the extra capacity earns much less.
- **Roof**: what physically fits.
- **Budget**: what they will spend.
"""

# Roof area per kWp. A 635 W module of about 2.69 m2 is roughly 4.2 m2/kWp of bare
# module, but a real array needs walkways, setbacks and - when tilted - row spacing so
# one row does not shade the next.
# ponytail: a stand-in until Phase 9 computes it from the actual panel layout, which is
# why the roof ceiling is reported as approximate.
PACKING_FACTOR = {
    "free": 1.7,      # elevated tilted rows need spacing between them
    "building": 1.2,  # flush mounted follows the roof, so little is wasted
}
DEFAULT_MODULE_AREA_PER_KWP_SQM = 4.5


def area_per_kwp_sqm(panel_length_mm=None, panel_width_mm=None, panel_wp=None,
                     mounting: str = "free") -> float:
    """Roof area one kWp occupies, from the module's own footprint where the catalog
    knows it, else a typical modern module."""
    module_area = DEFAULT_MODULE_AREA_PER_KWP_SQM
    if panel_length_mm and panel_width_mm and panel_wp:
        module_area = (panel_length_mm / 1000) * (panel_width_mm / 1000) / (panel_wp / 1000)
    return module_area * PACKING_FACTOR.get(mounting, PACKING_FACTOR["free"])


def recommend_capacity(specific_yield_kwh_per_kwp: float, annual_consumption_kwh=None,
                       roof_area_sqm=None, area_per_kwp=None, budget_inr=None,
                       cost_per_kwp_inr=None) -> dict:
    """The smallest ceiling that applies, and which one it was.

    Returns None for `recommended_kwp` when nothing constrains the size, rather than
    inventing a number.
    """
    ceilings = {}

    if annual_consumption_kwh and specific_yield_kwh_per_kwp > 0:
        ceilings["consumption"] = annual_consumption_kwh / specific_yield_kwh_per_kwp
    if roof_area_sqm and area_per_kwp:
        ceilings["roof"] = roof_area_sqm / area_per_kwp
    if budget_inr and cost_per_kwp_inr:
        ceilings["budget"] = budget_inr / cost_per_kwp_inr

    if not ceilings:
        return {"recommended_kwp": None, "limited_by": None, "ceilings_kwp": {}}

    limited_by = min(ceilings, key=ceilings.get)
    return {
        "recommended_kwp": round(ceilings[limited_by], 2),
        "limited_by": limited_by,
        "ceilings_kwp": {name: round(value, 2) for name, value in ceilings.items()},
    }
