from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database.session import Base


class IrradianceCache(Base):
    """PVGIS in-plane irradiation for one ~1 km grid cell and panel orientation."""

    __tablename__ = "irradiance_cache"
    # Doubles as the lookup index.
    __table_args__ = (
        UniqueConstraint("lat_key", "lon_key", "tilt_key", "azimuth_key", name="uq_irradiance_cell"),
    )

    id = Column(Integer, primary_key=True)

    # Integer keys (degrees x 100 for position, whole degrees for orientation) so
    # lookups never compare floats for equality.
    lat_key = Column(Integer, nullable=False)
    lon_key = Column(Integer, nullable=False)
    tilt_key = Column(Integer, nullable=False)
    azimuth_key = Column(Integer, nullable=False)

    monthly_h_json = Column(Text, nullable=False)  # 12 x H(i)_m, kWh/m2
    h_annual = Column(Float, nullable=False)       # H(i)_y, kWh/m2/yr
    radiation_db = Column(String, nullable=False)  # e.g. "PVGIS-ERA5"
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
