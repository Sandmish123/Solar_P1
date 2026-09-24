"""Component catalog access.

Visibility rule, in one place: a firm sees the shared seed rows (`org_id IS NULL`) plus
its own. It can only create and edit its own — the shared rows are read-only, so one
firm cannot change a model another firm is quoting.
"""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.components import InverterModel, PanelModel

MODELS = {"panel": PanelModel, "inverter": InverterModel}


def _visible(db: Session, model_class, org_id: int):
    return db.query(model_class).filter(
        or_(model_class.org_id.is_(None), model_class.org_id == org_id),
        model_class.is_active.is_(True),
    )


def list_components(db: Session, kind: str, org_id: int):
    model_class = MODELS[kind]
    return _visible(db, model_class, org_id).order_by(
        model_class.manufacturer, model_class.model
    ).all()


def get_component(db: Session, kind: str, component_id: int, org_id: int):
    """Shared or own, else None. Another firm's private component is invisible."""
    model_class = MODELS[kind]
    return _visible(db, model_class, org_id).filter(model_class.id == component_id).first()


def create_component(db: Session, kind: str, payload: dict, org_id: int):
    component = MODELS[kind](**payload, org_id=org_id)
    db.add(component)
    db.commit()
    db.refresh(component)
    return component


def update_component(db: Session, kind: str, component_id: int, payload: dict, org_id: int):
    """Returns the updated row, None if not found, or False if it is a shared row.

    Shared seed rows belong to no one and stay read-only; a firm that needs different
    values adds its own entry.
    """
    component = get_component(db, kind, component_id, org_id)
    if component is None:
        return None
    if component.org_id is None:
        return False

    for field, value in payload.items():
        setattr(component, field, value)
    db.commit()
    db.refresh(component)
    return component
