from sqlalchemy.orm import Session
from app.models.solar_project import SolarProject
from app.schemas.solar_project import ProjectCreate, ProjectUpdate
from app.calculations.financial import perform_financial_calculations
from app.calculations.solar import perform_all_calculations
from app.services.irradiance import get_irradiance


def get_project(db: Session, project_id: int):
    return db.query(SolarProject).filter(SolarProject.id == project_id).first()


def get_projects(db: Session, skip: int = 0, limit: int = 100):
    return db.query(SolarProject).offset(skip).limit(limit).all()


def create_project(db: Session, project: ProjectCreate):
    db_project = SolarProject(**project.model_dump())
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project


def update_project(db: Session, project_id: int, project: ProjectUpdate):
    db_project = get_project(db, project_id)
    if db_project:
        update_data = project.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_project, key, value)
        
        # Reset calculation status since parameters might have changed
        db_project.is_calculated = False
        db.commit()
        db.refresh(db_project)
    return db_project


async def calculate_project(db: Session, project_id: int):
    """Raises app.services.irradiance.InvalidLocationError if PVGIS rejects the site."""
    db_project = get_project(db, project_id)
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
    }

    irradiance = await get_irradiance(
        db, db_project.latitude, db_project.longitude, db_project.tilt_deg, db_project.azimuth_deg
    )
    results = perform_all_calculations(data, irradiance)
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


def delete_project(db: Session, project_id: int):
    db_project = get_project(db, project_id)
    if db_project:
        db.delete(db_project)
        db.commit()
        return True
    return False
