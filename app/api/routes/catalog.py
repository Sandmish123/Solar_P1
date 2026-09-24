from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.database.session import get_db
from app.models.user import User
from app.schemas.components import (
    InverterModelCreate,
    InverterModelResponse,
    InverterModelUpdate,
    PanelModelCreate,
    PanelModelResponse,
    PanelModelUpdate,
)
from app.services import catalog

router = APIRouter(prefix="/catalog", tags=["catalog"])

SHARED_ROW_MESSAGE = (
    "This is a shared catalog entry and cannot be edited. Add your own entry instead, "
    "so another firm's quotes are unaffected."
)


def _create(db, kind, payload, org_id):
    try:
        return catalog.create_component(db, kind, payload.model_dump(), org_id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"You already have a {kind} with that manufacturer and model")


def _update(db, kind, component_id, payload, org_id):
    result = catalog.update_component(db, kind, component_id, payload.model_dump(), org_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"{kind.capitalize()} not found")
    if result is False:
        raise HTTPException(status_code=403, detail=SHARED_ROW_MESSAGE)
    return result


@router.get("/panels", response_model=List[PanelModelResponse])
def list_panels(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return catalog.list_components(db, "panel", user.org_id)


@router.post("/panels", response_model=PanelModelResponse, status_code=201)
def create_panel(payload: PanelModelCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _create(db, "panel", payload, user.org_id)


@router.put("/panels/{panel_id}", response_model=PanelModelResponse)
def update_panel(panel_id: int, payload: PanelModelUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _update(db, "panel", panel_id, payload, user.org_id)


@router.get("/inverters", response_model=List[InverterModelResponse])
def list_inverters(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return catalog.list_components(db, "inverter", user.org_id)


@router.post("/inverters", response_model=InverterModelResponse, status_code=201)
def create_inverter(payload: InverterModelCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _create(db, "inverter", payload, user.org_id)


@router.put("/inverters/{inverter_id}", response_model=InverterModelResponse)
def update_inverter(inverter_id: int, payload: InverterModelUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _update(db, "inverter", inverter_id, payload, user.org_id)
