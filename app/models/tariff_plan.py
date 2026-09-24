from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import expression, func

from app.database.session import Base


class TariffPlan(Base):
    """A DISCOM rate card. `org_id` NULL would be a shared plan, a value is the firm's
    own — the same pattern as the component catalog.

    No plans ship with the app: rates vary by DISCOM, category and revision, and a
    stale tariff in a customer proposal is a commercial problem, not just a bug.
    """

    __tablename__ = "tariff_plans"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_tariff_plan"),
    )

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organisations.id"), nullable=True, index=True)

    name = Column(String, nullable=False)
    discom = Column(String, nullable=True)
    category = Column(String, nullable=True)   # e.g. "Domestic"

    # Telescopic bands: [{"upto": 50, "rate": 2.0}, ..., {"upto": null, "rate": 8.0}]
    slabs_json = Column(Text, nullable=False)
    # Recorded for completeness; excluded from savings because it does not change
    # when solar is added, so it cancels out of the difference.
    fixed_charge_inr_per_kw_month = Column(Float, nullable=True)

    is_active = Column(Boolean, nullable=False, server_default=expression.true())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
