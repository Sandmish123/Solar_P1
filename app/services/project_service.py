from sqlalchemy.orm import Session
from app.models.solar_project import SolarProject
from app.schemas.solar_project import ProjectCreate, ProjectUpdate
from app.calculations.solar import perform_all_calculations


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


def calculate_project(db: Session, project_id: int):
    db_project = get_project(db, project_id)
    if not db_project:
        return None
        
    # Extract data for calculation
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
    }
    
    results = perform_all_calculations(data)
    
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
