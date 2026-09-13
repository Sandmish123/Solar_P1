from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from starlette.responses import FileResponse
import os
import uuid

from app.database.session import get_db
from app.schemas.solar_project import ProjectCreate, ProjectUpdate, ProjectResponse
from app.services import project_service
from app.utils.pdf_generator import generate_project_pdf

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/", response_model=ProjectResponse, status_code=201)
def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    return project_service.create_project(db=db, project=project)


@router.get("/", response_model=List[ProjectResponse])
def read_projects(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return project_service.get_projects(db=db, skip=skip, limit=limit)


@router.get("/{project_id}", response_model=ProjectResponse)
def read_project(project_id: int, db: Session = Depends(get_db)):
    db_project = project_service.get_project(db, project_id=project_id)
    if db_project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return db_project


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: int, project: ProjectUpdate, db: Session = Depends(get_db)):
    db_project = project_service.update_project(db, project_id=project_id, project=project)
    if db_project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return db_project


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    success = project_service.delete_project(db, project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")


@router.post("/{project_id}/calculate", response_model=ProjectResponse)
def calculate_project(project_id: int, db: Session = Depends(get_db)):
    db_project = project_service.calculate_project(db, project_id=project_id)
    if db_project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return db_project


@router.get("/{project_id}/report/pdf")
def export_project_pdf(project_id: int, db: Session = Depends(get_db)):
    db_project = project_service.get_project(db, project_id=project_id)
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    if not db_project.is_calculated:
        raise HTTPException(status_code=400, detail="Project calculations must be run before generating PDF")
        
    # Ensure temp dir exists
    temp_dir = "./temp_pdfs"
    os.makedirs(temp_dir, exist_ok=True)
    
    file_path = os.path.join(temp_dir, f"solar_report_{project_id}_{uuid.uuid4().hex[:8]}.pdf")
    
    if generate_project_pdf(db_project, file_path):
        return FileResponse(path=file_path, filename=f"Energy_Report_{db_project.project_name.replace(' ', '_')}.pdf", media_type='application/pdf')
    else:
        raise HTTPException(status_code=500, detail="Error generating PDF report")
