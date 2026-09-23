from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, text
from sqlalchemy.sql import expression
from sqlalchemy.sql import func
from app.calculations.solar import DEFAULT_IRRADIANCE_CALIBRATION
from app.database.session import Base


class SolarProject(Base):
    __tablename__ = "solar_projects"

    id = Column(Integer, primary_key=True, index=True)
    
    # Project Info
    project_name = Column(String, index=True)
    client_name = Column(String, index=True)
    site_address = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    date = Column(String)
    
    # System Config
    num_panels = Column(Integer)
    panel_wattage = Column(Float)
    panel_model = Column(String)
    inverter_model = Column(String)
    roof_area_sqm = Column(Float)
    degradation_rate = Column(Float, default=0.7)  # 0.7% default

    # Orientation and irradiance. server_default backfills rows that predate them.
    tilt_deg = Column(Float, default=25.0, server_default=text("25.0"))
    azimuth_deg = Column(Float, default=0.0, server_default=text("0.0"))  # 0 = south, -90 = east, +90 = west
    irradiance_calibration = Column(
        Float,
        default=DEFAULT_IRRADIANCE_CALIBRATION,
        server_default=text(str(DEFAULT_IRRADIANCE_CALIBRATION)),
    )

    # Loss Parameters
    temp_loss_pct = Column(Float, default=11.5)
    shading_loss_pct = Column(Float, default=0.0)
    # Off by default: turning it on would silently change every existing proposal.
    shading_auto = Column(Boolean, default=False, server_default=expression.false())
    soiling_loss_pct = Column(Float, default=3.0)
    inverter_loss_pct = Column(Float, default=3.0)
    mismatch_loss_pct = Column(Float, default=2.0)
    dc_wiring_loss_pct = Column(Float, default=2.0)
    ac_wiring_loss_pct = Column(Float, default=0.0)

    # Financial inputs (INR). No system cost means no financials, never an invented one.
    system_cost_inr = Column(Float, nullable=True)
    subsidy_inr = Column(Float, nullable=True)  # override; None = PM Surya Ghar auto
    tariff_inr_per_kwh = Column(Float, default=8.0, server_default=text("8.0"))
    tariff_escalation_pct = Column(Float, default=3.0, server_default=text("3.0"))
    export_ratio_pct = Column(Float, default=30.0, server_default=text("30.0"))
    export_tariff_inr_per_kwh = Column(Float, default=3.0, server_default=text("3.0"))
    om_cost_pct = Column(Float, default=1.0, server_default=text("1.0"))
    discount_rate_pct = Column(Float, default=8.0, server_default=text("8.0"))
    # 0 disables; cost defaults to a share of system cost when not given.
    inverter_replacement_year = Column(Integer, default=12, server_default=text("12"))
    inverter_replacement_cost_inr = Column(Float, nullable=True)

    # Calculation Results
    capacity_kwp = Column(Float, nullable=True)
    annual_gen_kwh = Column(Float, nullable=True)
    specific_yield = Column(Float, nullable=True)
    performance_ratio = Column(Float, nullable=True)
    total_system_loss = Column(Float, nullable=True)
    lifetime_gen_mwh = Column(Float, nullable=True)
    year25_output_mwh = Column(Float, nullable=True)
    monthly_gen_json = Column(Text, nullable=True)  # Store as JSON string
    irradiance_source = Column(String, nullable=True)  # "pvgis" | "fallback"
    irradiance_h_annual = Column(Float, nullable=True)  # H(i)_y used, before calibration

    # Financial results
    subsidy_applied_inr = Column(Float, nullable=True)
    net_investment_inr = Column(Float, nullable=True)
    year1_savings_inr = Column(Float, nullable=True)
    payback_years = Column(Float, nullable=True)  # None = not within 25 years
    discounted_payback_years = Column(Float, nullable=True)
    irr_pct = Column(Float, nullable=True)
    npv_inr = Column(Float, nullable=True)
    lifetime_net_savings_inr = Column(Float, nullable=True)
    lcoe_inr_per_kwh = Column(Float, nullable=True)
    co2_offset_tonnes = Column(Float, nullable=True)
    inverter_replacement_applied_inr = Column(Float, nullable=True)
    cashflow_json = Column(Text, nullable=True)  # 25 yearly rows, JSON string

    # Shading estimated from OSM geometry (always reported; applied only when shading_auto)
    shading_computed_pct = Column(Float, nullable=True)
    shading_neighbour_count = Column(Integer, nullable=True)
    shading_heights_assumed = Column(Integer, nullable=True)
    shading_monthly_json = Column(Text, nullable=True)

    # Metadata
    is_calculated = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
