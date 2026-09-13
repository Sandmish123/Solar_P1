from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Dict, List
from datetime import datetime


class ProjectBase(BaseModel):
    project_name: str
    client_name: str
    site_address: str
    latitude: float
    longitude: float
    date: str
    
    num_panels: int = Field(gt=0)
    panel_wattage: float = Field(gt=0, description="Wattage per panel in W")
    panel_model: str
    inverter_model: str
    roof_area_sqm: float = Field(gt=0)
    degradation_rate: float = 0.7
    
    temp_loss_pct: float = 11.5
    shading_loss_pct: float = 0.0
    soiling_loss_pct: float = 3.0
    inverter_loss_pct: float = 3.0
    mismatch_loss_pct: float = 2.0
    dc_wiring_loss_pct: float = 2.0
    ac_wiring_loss_pct: float = 0.0


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(ProjectBase):
    pass


class ProjectResponse(ProjectBase):
    id: int
    
    capacity_kwp: Optional[float] = None
    annual_gen_kwh: Optional[float] = None
    specific_yield: Optional[float] = None
    performance_ratio: Optional[float] = None
    total_system_loss: Optional[float] = None
    lifetime_gen_mwh: Optional[float] = None
    year25_output_mwh: Optional[float] = None
    monthly_gen_json: Optional[str] = None
    
    is_calculated: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
