from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.sql import func
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
    
    # Loss Parameters
    temp_loss_pct = Column(Float, default=11.5)
    shading_loss_pct = Column(Float, default=0.0)
    soiling_loss_pct = Column(Float, default=3.0)
    inverter_loss_pct = Column(Float, default=3.0)
    mismatch_loss_pct = Column(Float, default=2.0)
    dc_wiring_loss_pct = Column(Float, default=2.0)
    ac_wiring_loss_pct = Column(Float, default=0.0)
    
    # Calculation Results
    capacity_kwp = Column(Float, nullable=True)
    annual_gen_kwh = Column(Float, nullable=True)
    specific_yield = Column(Float, nullable=True)
    performance_ratio = Column(Float, nullable=True)
    total_system_loss = Column(Float, nullable=True)
    lifetime_gen_mwh = Column(Float, nullable=True)
    year25_output_mwh = Column(Float, nullable=True)
    monthly_gen_json = Column(Text, nullable=True)  # Store as JSON string
    
    # Metadata
    is_calculated = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
