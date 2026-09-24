import json

from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models.solar_project import SolarProject
from app.schemas.solar_project import ProjectCreate, ProjectUpdate
from app.calculations.financial import perform_financial_calculations
from app.calculations.shading import DEFAULT_ARRAY_HEIGHT_M, compute_shading, find_host_height
from app.calculations.solar import perform_all_calculations
from app.services.buildings import get_buildings
from app.services.irradiance import get_irradiance


def get_project(db: Session, project_id: int, org_id: int):
    """Scoped by organisation. Every other function goes through here, so a project
    from another firm is indistinguishable from one that does not exist."""
    return db.query(SolarProject).filter(
        SolarProject.id == project_id,
        SolarProject.org_id == org_id,
    ).first()


def get_projects(db: Session, org_id: int, skip: int = 0, limit: int = 100, search: str = None):
    """Newest first. `search` matches project or client name, case-insensitively.
    ponytail: leading-wildcard LIKE can't use the name indexes; fine at proposal
    volumes, revisit with a trigram index if the dashboard ever feels slow."""
    query = db.query(SolarProject).filter(SolarProject.org_id == org_id)
    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(
            SolarProject.project_name.ilike(pattern),
            SolarProject.client_name.ilike(pattern),
        ))
    return query.order_by(SolarProject.created_at.desc(), SolarProject.id.desc()).offset(skip).limit(limit).all()


def create_project(db: Session, project: ProjectCreate, org_id: int):
    db_project = SolarProject(**project.model_dump(), org_id=org_id)
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project


def update_project(db: Session, project_id: int, project: ProjectUpdate, org_id: int):
    db_project = get_project(db, project_id, org_id)
    if db_project:
        # PUT is a full replace: an omitted optional field is cleared, not kept.
        # The edit form always sends every field. Partial updates would be a PATCH.
        update_data = project.model_dump()
        for key, value in update_data.items():
            setattr(db_project, key, value)
        
        # Reset calculation status since parameters might have changed
        db_project.is_calculated = False
        db.commit()
        db.refresh(db_project)
    return db_project


async def calculate_project(db: Session, project_id: int, org_id: int):
    """Raises app.services.irradiance.InvalidLocationError if PVGIS rejects the site."""
    db_project = get_project(db, project_id, org_id)
    if not db_project:
        return None

    # Extract data for calculation. Read before get_irradiance: a cache-write
    # rollback there expires db_project's loaded attributes.
    data = {
        "num_panels": db_project.num_panels,
        "panel_wattage": db_project.panel_wattage,
        "degradation_rate": db_project.degradation_rate,
        "temp_loss_pct": db_project.temp_loss_pct,
        "shading_loss_pct": db_project.shading_loss_pct,
        "soiling_loss_pct": db_project.soiling_loss_pct,
        "inverter_loss_pct": db_project.inverter_loss_pct,
        "mismatch_loss_pct": db_project.mismatch_loss_pct,
        "dc_wiring_loss_pct": db_project.dc_wiring_loss_pct,
        "ac_wiring_loss_pct": db_project.ac_wiring_loss_pct,
        "irradiance_calibration": db_project.irradiance_calibration,
    }
    financial_inputs = {
        "system_cost_inr": db_project.system_cost_inr,
        "subsidy_inr": db_project.subsidy_inr,
        "tariff_inr_per_kwh": db_project.tariff_inr_per_kwh,
        "tariff_escalation_pct": db_project.tariff_escalation_pct,
        "export_ratio_pct": db_project.export_ratio_pct,
        "export_tariff_inr_per_kwh": db_project.export_tariff_inr_per_kwh,
        "om_cost_pct": db_project.om_cost_pct,
        "discount_rate_pct": db_project.discount_rate_pct,
        "inverter_replacement_year": db_project.inverter_replacement_year,
        "inverter_replacement_cost_inr": db_project.inverter_replacement_cost_inr,
    }

    shading = await _estimate_shading(db, db_project) if db_project.shading_auto else None
    if shading:
        # Replaces the operator's figure only while shading_auto is on.
        data["shading_loss_pct"] = shading["annual_pct"]

    irradiance = await get_irradiance(
        db, db_project.latitude, db_project.longitude, db_project.tilt_deg, db_project.azimuth_deg
    )
    results = perform_all_calculations(data, irradiance)
    results.update({
        "shading_loss_pct": data["shading_loss_pct"],
        "shading_computed_pct": shading["annual_pct"] if shading else None,
        "shading_neighbour_count": shading["neighbour_count"] if shading else None,
        "shading_heights_assumed": shading["heights_assumed"] if shading else None,
        "shading_monthly_json": json.dumps(shading["monthly_pct"]) if shading else None,
    })
    # Always written, so removing the system cost clears stale financials.
    results.update(perform_financial_calculations(
        financial_inputs, results["capacity_kwp"], results["annual_gen_kwh"], data["degradation_rate"]
    ))

    # Update project with results
    for key, value in results.items():
        setattr(db_project, key, value)
        
    db.commit()
    db.refresh(db_project)
    return db_project


async def _estimate_shading(db: Session, db_project):
    """Shading from the buildings around the site, or None if Overpass is unreachable."""
    buildings = await get_buildings(db, db_project.latitude, db_project.longitude)
    if buildings is None:
        return None
    array_height = find_host_height(buildings, db_project.latitude, db_project.longitude)
    return compute_shading(
        buildings,
        db_project.latitude,
        db_project.longitude,
        db_project.tilt_deg,
        db_project.azimuth_deg,
        array_height if array_height is not None else DEFAULT_ARRAY_HEIGHT_M,
    )


def delete_project(db: Session, project_id: int, org_id: int):
    db_project = get_project(db, project_id, org_id)
    if db_project:
        db.delete(db_project)
        db.commit()
        return True
    return False
