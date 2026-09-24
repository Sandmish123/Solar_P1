import json

from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models.solar_project import SolarProject
from app.schemas.solar_project import ProjectCreate, ProjectUpdate
from app.calculations.compliance import blocks_subsidy, check_compliance, to_dicts
from app.calculations.financial import perform_financial_calculations
from app.calculations.shading import DEFAULT_ARRAY_HEIGHT_M, compute_shading, find_host_height
from app.calculations.sizing import area_per_kwp_sqm, recommend_capacity
from app.calculations.tariff import slab_bill
from app.calculations.solar import perform_all_calculations
from app.services import catalog
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
        "temp_loss_auto": db_project.temp_loss_auto,
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

    consumption_units, entered_annual_bill = _parse_consumption(db_project.consumption_json)
    tariff_plan = _component(db, "tariff", db_project.tariff_plan_id, org_id)
    slabs = json.loads(tariff_plan.slabs_json) if tariff_plan else None
    # Both are needed: a tariff without consumption cannot be settled, and consumption
    # without a tariff cannot be priced. Either missing falls back to the flat estimate.
    financial_inputs["monthly_consumption"] = consumption_units
    financial_inputs["tariff_slabs"] = slabs

    # Components and compliance first: both are plain DB reads, and resolving them
    # before the awaits below means nothing here depends on ORM objects that a cache
    # write inside get_irradiance could expire.
    panel = _component(db, "panel", db_project.panel_model_id, org_id)
    inverter = _component(db, "inverter", db_project.inverter_model_id, org_id)
    panel_dimensions = (panel.length_mm, panel.width_mm, panel.wp) if panel else (None, None, None)
    if panel is not None:
        # The catalog is the source of truth once a model is chosen.
        data["panel_wattage"] = panel.wp

    claiming_subsidy = financial_inputs["system_cost_inr"] is not None and (
        financial_inputs["subsidy_inr"] is None or financial_inputs["subsidy_inr"] > 0
    )
    issues = check_compliance(panel, inverter, claiming_subsidy=claiming_subsidy)
    if blocks_subsidy(issues):
        # Not merely hidden on the PDF: a payback built on a subsidy the customer
        # cannot evidence would overstate the return.
        financial_inputs["subsidy_inr"] = 0.0
    compliance_payload = to_dicts(issues)
    panel_wattage = data["panel_wattage"]

    shading = await _estimate_shading(db, db_project) if db_project.shading_auto else None
    if shading:
        # Replaces the operator's figure only while shading_auto is on.
        data["shading_loss_pct"] = shading["annual_pct"]

    irradiance = await get_irradiance(
        db, db_project.latitude, db_project.longitude, db_project.tilt_deg,
        db_project.azimuth_deg, db_project.mounting_type,
    )
    if db_project.temp_loss_auto and irradiance.get("temp_loss_pct"):
        # Replaces the operator's figure only while temp_loss_auto is on, and only
        # when the dataset actually supplied one.
        data["temp_loss_pct"] = irradiance["temp_loss_pct"]

    results = perform_all_calculations(data, irradiance, shading)
    results.update({
        "panel_wattage": panel_wattage,
        "temp_loss_pct": data["temp_loss_pct"],
        "temp_loss_computed_pct": irradiance.get("temp_loss_pct"),
        "compliance_json": json.dumps(compliance_payload) if compliance_payload else None,
        "shading_loss_pct": data["shading_loss_pct"],
        "shading_computed_pct": shading["annual_pct"] if shading else None,
        "shading_neighbour_count": shading["neighbour_count"] if shading else None,
        "shading_heights_assumed": shading["heights_assumed"] if shading else None,
        "shading_monthly_json": json.dumps(shading["monthly_pct"]) if shading else None,
    })
    # Always written, so removing the system cost clears stale financials.
    results.update(perform_financial_calculations(
        financial_inputs, results["capacity_kwp"], results["annual_gen_kwh"],
        data["degradation_rate"], _monthly_share(results["monthly_gen_json"]),
    ))

    sizing = recommend_capacity(
        specific_yield_kwh_per_kwp=results["specific_yield"],
        annual_consumption_kwh=sum(consumption_units) if consumption_units else None,
        roof_area_sqm=db_project.roof_area_sqm,
        area_per_kwp=area_per_kwp_sqm(*panel_dimensions, mounting=db_project.mounting_type),
        budget_inr=db_project.budget_inr,
        cost_per_kwp_inr=(
            financial_inputs["system_cost_inr"] / results["capacity_kwp"]
            if financial_inputs["system_cost_inr"] and results["capacity_kwp"] else None
        ),
    )
    results["recommended_kwp"] = sizing["recommended_kwp"]
    results["sizing_json"] = json.dumps(sizing) if sizing["recommended_kwp"] else None
    results["tariff_check_json"] = _check_tariff(consumption_units, slabs, entered_annual_bill)

    # Update project with results
    for key, value in results.items():
        setattr(db_project, key, value)
        
    db.commit()
    db.refresh(db_project)
    return db_project


def _parse_consumption(consumption_json):
    """(monthly units, entered annual bill) or (None, None). The schema has already
    validated the shape, so this only reads it."""
    if not consumption_json:
        return None, None
    months = json.loads(consumption_json)
    units = [float(month["units"]) for month in months]
    bills = [month.get("bill_inr") for month in months]
    entered_bill = sum(bills) if all(bill is not None for bill in bills) else None
    # All-zero consumption tells us nothing, so treat it as not supplied.
    return (units, entered_bill) if sum(units) > 0 else (None, None)


def _monthly_share(monthly_gen_json):
    """The year's generation as 12 fractions, for settling month by month."""
    months = json.loads(monthly_gen_json)
    total = sum(month["value_kwh"] for month in months)
    return [month["value_kwh"] / total for month in months] if total > 0 else None


def _check_tariff(consumption_units, slabs, entered_annual_bill):
    """Compare the modelled bill with the one the customer actually pays. A large gap
    usually means the wrong tariff plan, which would quietly skew every saving."""
    if not (consumption_units and slabs and entered_annual_bill):
        return None
    modelled = sum(slab_bill(units, slabs) for units in consumption_units)
    deviation = (modelled - entered_annual_bill) / entered_annual_bill * 100
    return json.dumps({
        "entered_annual_bill_inr": round(entered_annual_bill),
        "modelled_annual_bill_inr": round(modelled),
        "deviation_pct": round(deviation, 1),
    })


def _component(db: Session, kind: str, component_id, org_id: int):
    """A catalog row the firm can see, or None when the project predates the catalog."""
    if component_id is None:
        return None
    return catalog.get_component(db, kind, component_id, org_id)


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
