from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.database.session import Base


class Organisation(Base):
    """One EPC firm. Every project and every catalog addition belongs to exactly one."""

    __tablename__ = "organisations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
