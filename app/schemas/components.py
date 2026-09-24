from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PanelModelBase(BaseModel):
    manufacturer: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=160)
    wp: float = Field(gt=0, le=2000)

    # Datasheet values. Optional because the seed cannot know them, but bounded so a
    # typo cannot reach Phase 10's string sizing.
    voc: Optional[float] = Field(None, gt=0, le=200)
    isc: Optional[float] = Field(None, gt=0, le=100)
    vmp: Optional[float] = Field(None, gt=0, le=200)
    imp: Optional[float] = Field(None, gt=0, le=100)
    # Negative by definition: output falls as the cell warms.
    temp_coeff_voc_pct_per_c: Optional[float] = Field(None, ge=-1.0, le=0.0)
    temp_coeff_pmax_pct_per_c: Optional[float] = Field(None, ge=-1.0, le=0.0)
    length_mm: Optional[float] = Field(None, gt=0, le=5000)
    width_mm: Optional[float] = Field(None, gt=0, le=5000)
    efficiency_pct: Optional[float] = Field(None, gt=0, le=100)

    # Tri-state: None means "not recorded", which blocks a subsidy rather than passing.
    almm_listed: Optional[bool] = None
    almm_id: Optional[str] = Field(None, max_length=64)
    dcr: Optional[bool] = None

    is_bifacial: Optional[bool] = None
    datasheet_verified: bool = False


class PanelModelCreate(PanelModelBase):
    pass


class PanelModelUpdate(PanelModelBase):
    """Full replace, like ProjectUpdate."""


class PanelModelResponse(PanelModelBase):
    id: int
    org_id: Optional[int] = None  # null = shared seed row, read-only
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class InverterModelBase(BaseModel):
    manufacturer: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=160)
    ac_kw: Optional[float] = Field(None, gt=0, le=1000)

    max_dc_v: Optional[float] = Field(None, gt=0, le=2000)
    start_v: Optional[float] = Field(None, gt=0, le=2000)
    mppt_count: Optional[int] = Field(None, ge=1, le=24)
    mppt_v_min: Optional[float] = Field(None, gt=0, le=2000)
    mppt_v_max: Optional[float] = Field(None, gt=0, le=2000)
    max_input_current_per_mppt: Optional[float] = Field(None, gt=0, le=100)
    max_isc_per_mppt: Optional[float] = Field(None, gt=0, le=100)
    phases: Optional[int] = Field(None, ge=1, le=3)
    efficiency_pct: Optional[float] = Field(None, gt=0, le=100)

    # Informational: no inverter compliance rule is asserted by this app.
    bis_certified: Optional[bool] = None
    datasheet_verified: bool = False


class InverterModelCreate(InverterModelBase):
    pass


class InverterModelUpdate(InverterModelBase):
    """Full replace, like ProjectUpdate."""


class InverterModelResponse(InverterModelBase):
    id: int
    org_id: Optional[int] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class ComplianceIssue(BaseModel):
    code: str
    severity: str
    message: str
