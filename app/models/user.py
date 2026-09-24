from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.sql import expression, func

from app.database.session import Base


class User(Base):
    """A person who signs in. Email is unique across the install, so login needs no
    organisation prompt."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organisations.id"), nullable=False, index=True)

    email = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=True)
    role = Column(String, nullable=False, server_default=text("'member'"))  # member | admin
    # expression.true() renders as 1 on SQLite and true on Postgres.
    is_active = Column(Boolean, nullable=False, server_default=expression.true())

    created_at = Column(DateTime(timezone=True), server_default=func.now())
