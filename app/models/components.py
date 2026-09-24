"""Panel and inverter catalog.

`org_id` is nullable on purpose: **null is the shared seed catalog, set is that firm's
own additions.** One table, no per-tenant duplication of the models everyone sells.

Electrical fields are nullable because the seed ships only what can be known without a
datasheet (manufacturer, model, watts). Voc and Isc feed string sizing in Phase 10,
where a wrong number oversizes a string and damages an inverter, so they are left empty
rather than guessed. `datasheet_verified` records whether a human has checked them.

The compliance flags are deliberately tri-state: True, False, or NULL for "not
recorded". NULL must never read as compliant.
"""
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import expression, func

from app.database.session import Base


class PanelModel(Base):
    __tablename__ = "panel_models"
    __table_args__ = (
        UniqueConstraint("org_id", "manufacturer", "model", name="uq_panel_model"),
    )

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organisations.id"), nullable=True, index=True)

    manufacturer = Column(String, nullable=False)
    model = Column(String, nullable=False)
    wp = Column(Float, nullable=False)

    # From the datasheet; needed for stringing and layout.
    voc = Column(Float, nullable=True)
    isc = Column(Float, nullable=True)
    vmp = Column(Float, nullable=True)
    imp = Column(Float, nullable=True)
    temp_coeff_voc_pct_per_c = Column(Float, nullable=True)   # negative, e.g. -0.27
    temp_coeff_pmax_pct_per_c = Column(Float, nullable=True)  # negative, e.g. -0.34
    length_mm = Column(Float, nullable=True)
    width_mm = Column(Float, nullable=True)
    efficiency_pct = Column(Float, nullable=True)

    # Compliance. NULL = not recorded, which blocks rather than passes.
    almm_listed = Column(Boolean, nullable=True)
    almm_id = Column(String, nullable=True)
    dcr = Column(Boolean, nullable=True)

    is_bifacial = Column(Boolean, nullable=True)
    datasheet_verified = Column(Boolean, nullable=False, server_default=expression.false())
    is_active = Column(Boolean, nullable=False, server_default=expression.true())
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class InverterModel(Base):
    __tablename__ = "inverter_models"
    __table_args__ = (
        UniqueConstraint("org_id", "manufacturer", "model", name="uq_inverter_model"),
    )

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organisations.id"), nullable=True, index=True)

    manufacturer = Column(String, nullable=False)
    model = Column(String, nullable=False)
    # Nullable for the same reason as the electrical fields: the seed carries only what
    # a model designation reveals, and an inverter's rating is not always in its name.
    ac_kw = Column(Float, nullable=True)

    max_dc_v = Column(Float, nullable=True)
    start_v = Column(Float, nullable=True)
    mppt_count = Column(Integer, nullable=True)
    mppt_v_min = Column(Float, nullable=True)
    mppt_v_max = Column(Float, nullable=True)
    max_input_current_per_mppt = Column(Float, nullable=True)
    max_isc_per_mppt = Column(Float, nullable=True)
    phases = Column(Integer, nullable=True)
    efficiency_pct = Column(Float, nullable=True)

    # Informational only. ALMM List-I covers modules; no inverter rule is asserted
    # here because none was verified against a primary source.
    bis_certified = Column(Boolean, nullable=True)

    datasheet_verified = Column(Boolean, nullable=False, server_default=expression.false())
    is_active = Column(Boolean, nullable=False, server_default=expression.true())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
