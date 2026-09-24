from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.sql import func

from app.database.session import Base


class IrradianceCache(Base):
    """PVGIS in-plane irradiation for one ~1 km grid cell and panel orientation."""

    __tablename__ = "irradiance_cache"
    # Doubles as the lookup index.
    # Mounting is part of the key: it does not change irradiation, but it changes the
    # temperature loss PVGIS reports alongside it.
    __table_args__ = (
        UniqueConstraint("lat_key", "lon_key", "tilt_key", "azimuth_key", "mounting", name="uq_irradiance_cell"),
    )

    id = Column(Integer, primary_key=True)

    # Integer keys (degrees x 100 for position, whole degrees for orientation) so
    # lookups never compare floats for equality.
    lat_key = Column(Integer, nullable=False)
    lon_key = Column(Integer, nullable=False)
    tilt_key = Column(Integer, nullable=False)
    azimuth_key = Column(Integer, nullable=False)

    mounting = Column(String, nullable=False, server_default=text("'free'"))

    monthly_h_json = Column(Text, nullable=False)  # 12 x H(i)_m, kWh/m2
    h_annual = Column(Float, nullable=False)       # H(i)_y, kWh/m2/yr
    radiation_db = Column(String, nullable=False)  # e.g. "PVGIS-ERA5"

    # For P90 and the site temperature loss. Nullable: rows cached before Phase 7 have
    # none, and the fallback profile never has any.
    e_annual = Column(Float, nullable=True)        # E_y, kWh/kWp/yr
    sd_annual = Column(Float, nullable=True)       # SD_y, interannual standard deviation
    temp_loss_pct = Column(Float, nullable=True)   # abs(l_tg): temperature + low irradiance
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
