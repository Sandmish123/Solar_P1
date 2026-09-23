from sqlalchemy import Column, DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database.session import Base


class BuildingCache(Base):
    """OSM building footprints around one ~11 m cell, for shading geometry."""

    __tablename__ = "building_cache"
    # Doubles as the lookup index.
    __table_args__ = (
        UniqueConstraint("lat_key", "lon_key", "radius_m", name="uq_building_cell"),
    )

    id = Column(Integer, primary_key=True)

    # Integer keys (degrees x 10000, ~11 m) so lookups never compare floats. Finer
    # than the irradiance grid: which buildings shade you changes street by street.
    lat_key = Column(Integer, nullable=False)
    lon_key = Column(Integer, nullable=False)
    radius_m = Column(Integer, nullable=False)

    buildings_json = Column(Text, nullable=False)  # [{polygon, height_m, height_source}]
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
