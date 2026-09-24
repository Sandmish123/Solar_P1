"""Every model, imported here so the metadata is always complete.

SQLAlchemy resolves a ForeignKey by table name at mapper-configuration time, so
importing one model without its referents fails with NoReferencedTableError. Importing
any model now pulls in the whole set, which keeps scripts, migrations and the app from
each having to remember the list.
"""
from app.models.building_cache import BuildingCache
from app.models.components import InverterModel, PanelModel
from app.models.irradiance_cache import IrradianceCache
from app.models.organisation import Organisation
from app.models.solar_project import SolarProject
from app.models.user import User

__all__ = [
    "BuildingCache",
    "InverterModel",
    "IrradianceCache",
    "Organisation",
    "PanelModel",
    "SolarProject",
    "User",
]
