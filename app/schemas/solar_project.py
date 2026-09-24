import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, Dict, List
from datetime import datetime

from app.calculations.solar import DEFAULT_IRRADIANCE_CALIBRATION


class ProjectBase(BaseModel):
    project_name: str
    client_name: str
    site_address: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    date: str
    
    num_panels: int = Field(gt=0)
    panel_wattage: float = Field(gt=0, description="Wattage per panel in W")
    panel_model: str
    panel_model_id: Optional[int] = Field(None, description="Catalog panel; overrides panel_wattage when set")
    inverter_model_id: Optional[int] = None
    inverter_model: str
    roof_area_sqm: float = Field(gt=0)
    degradation_rate: float = 0.7

    tilt_deg: float = Field(25.0, ge=0, le=90)
    azimuth_deg: float = Field(0.0, ge=-180, le=180, description="0 = south, -90 = east, +90 = west")
    # Bounded so a typo (83 for 0.83) fails validation instead of reaching a customer.
    irradiance_calibration: float = Field(DEFAULT_IRRADIANCE_CALIBRATION, ge=0.5, le=1.5)

    temp_loss_pct: float = 11.5
    temp_loss_auto: bool = Field(False, description="Derive temperature loss from PVGIS for this site")
    mounting_type: Literal["free", "building"] = Field("free", description="free = elevated racking, building = flush mounted")
    shading_loss_pct: float = 0.0
    shading_auto: bool = Field(False, description="Estimate shading from OSM building geometry instead of using shading_loss_pct")
    soiling_loss_pct: float = 3.0
    inverter_loss_pct: float = 3.0
    mismatch_loss_pct: float = 2.0
    dc_wiring_loss_pct: float = 2.0
    ac_wiring_loss_pct: float = 0.0

    system_cost_inr: Optional[float] = Field(None, gt=0, le=1e9, description="Total installed cost; financials are skipped when absent")
    subsidy_inr: Optional[float] = Field(None, ge=0, le=1e9, description="Overrides the PM Surya Ghar auto-calculation; 0 for non-residential")
    tariff_inr_per_kwh: float = Field(8.0, gt=0, le=50)
    tariff_escalation_pct: float = Field(3.0, ge=0, le=20)
    export_ratio_pct: float = Field(30.0, ge=0, le=100, description="Annual surplus paid at the export tariff, % of generation")
    export_tariff_inr_per_kwh: float = Field(3.0, ge=0, le=50)
    consumption_json: Optional[str] = Field(None, description="12 months of {units, bill_inr}")

    @field_validator("consumption_json")
    @classmethod
    def _twelve_valid_months(cls, value):
        """Validated at the boundary rather than trusted: a short or negative series
        would silently skew the whole savings model."""
        if value in (None, ""):
            return None
        try:
            months = json.loads(value)
        except (TypeError, ValueError):
            raise ValueError("consumption must be valid JSON")
        if not isinstance(months, list) or len(months) != 12:
            raise ValueError("consumption needs exactly 12 months")
        for index, month in enumerate(months):
            if not isinstance(month, dict):
                raise ValueError(f"month {index + 1} is not an object")
            units = month.get("units")
            if units is None or not isinstance(units, (int, float)) or units < 0:
                raise ValueError(f"month {index + 1} needs units of 0 or more")
            bill = month.get("bill_inr")
            if bill is not None and (not isinstance(bill, (int, float)) or bill < 0):
                raise ValueError(f"month {index + 1} has a negative bill")
        return value
    tariff_plan_id: Optional[int] = None
    budget_inr: Optional[float] = Field(None, gt=0, le=1e9)
    om_cost_pct: float = Field(1.0, ge=0, le=10, description="Annual O&M, % of system cost")
    discount_rate_pct: float = Field(8.0, ge=0, le=30)
    inverter_replacement_year: int = Field(12, ge=0, le=25, description="Year the inverter is replaced; 0 disables")
    inverter_replacement_cost_inr: Optional[float] = Field(None, gt=0, le=1e9, description="Overrides the default share of system cost")


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(ProjectBase):
    """Full replace: every required field must be sent, and omitted optional fields
    are cleared."""


class ProjectResponse(ProjectBase):
    id: int
    org_id: int
    
    capacity_kwp: Optional[float] = None
    annual_gen_kwh: Optional[float] = None
    specific_yield: Optional[float] = None
    performance_ratio: Optional[float] = None
    total_system_loss: Optional[float] = None
    lifetime_gen_mwh: Optional[float] = None
    year25_output_mwh: Optional[float] = None
    monthly_gen_json: Optional[str] = None
    irradiance_source: Optional[str] = None
    irradiance_h_annual: Optional[float] = None

    subsidy_applied_inr: Optional[float] = None
    net_investment_inr: Optional[float] = None
    year1_savings_inr: Optional[float] = None
    payback_years: Optional[float] = None
    discounted_payback_years: Optional[float] = None
    irr_pct: Optional[float] = None
    npv_inr: Optional[float] = None
    lifetime_net_savings_inr: Optional[float] = None
    lcoe_inr_per_kwh: Optional[float] = None
    co2_offset_tonnes: Optional[float] = None
    inverter_replacement_applied_inr: Optional[float] = None
    cashflow_json: Optional[str] = None
    shading_computed_pct: Optional[float] = None
    shading_neighbour_count: Optional[int] = None
    shading_heights_assumed: Optional[int] = None
    shading_monthly_json: Optional[str] = None
    compliance_json: Optional[str] = None
    annual_gen_p90_kwh: Optional[float] = None
    temp_loss_computed_pct: Optional[float] = None
    savings_basis: Optional[str] = None
    self_consumed_kwh: Optional[float] = None
    exported_kwh: Optional[float] = None
    effective_rate_inr_per_kwh: Optional[float] = None
    recommended_kwp: Optional[float] = None
    sizing_json: Optional[str] = None
    tariff_check_json: Optional[str] = None

    is_calculated: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
