import base64
import glob
import json
import re
import zlib

import httpx
import pytest

from app.services import buildings, irradiance
from app.services.irradiance import InvalidLocationError
from app.utils.pdf_generator import format_inr


def _pdf_text(pdf_bytes):
    """Drawn text of a ReportLab PDF: streams are ASCII85 over Flate, and PDF
    string syntax escapes parentheses."""
    chunks = []
    for stream in re.findall(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.S):
        stream = stream.strip()
        if stream.endswith(b"~>"):
            stream = base64.a85decode(stream, adobe=True)
        try:
            stream = zlib.decompress(stream)
        except zlib.error:
            pass
        chunks.append(stream)
    return b"".join(chunks).decode("latin-1").replace("\\(", "(").replace("\\)", ")")


def _calculated_project(client, payload):
    created = client.post("/api/projects/", json=payload)
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    calculated = client.post(f"/api/projects/{project_id}/calculate")
    assert calculated.status_code == 200, calculated.text
    return project_id


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_create_calculate_fetch(client, project_payload):
    project_id = _calculated_project(client, project_payload)

    fetched = client.get(f"/api/projects/{project_id}").json()
    assert fetched["is_calculated"] is True
    assert fetched["capacity_kwp"] == 9.525
    assert fetched["irradiance_source"] == "pvgis"
    assert fetched["specific_yield"] == pytest.approx(1401, abs=0.5)
    assert fetched["subsidy_applied_inr"] == 78_000
    assert fetched["payback_years"] == pytest.approx(5.2, abs=0.1)
    assert len(fetched["cashflow_json"]) > 0


def test_no_system_cost_skips_financials(client, project_payload):
    del project_payload["system_cost_inr"]
    project_id = _calculated_project(client, project_payload)

    fetched = client.get(f"/api/projects/{project_id}").json()
    assert fetched["specific_yield"] == pytest.approx(1401, abs=0.5)
    assert fetched["net_investment_inr"] is None
    assert fetched["cashflow_json"] is None

    pdf = client.get(f"/api/projects/{project_id}/report/pdf")
    assert pdf.status_code == 200
    assert "FINANCIAL SUMMARY" not in _pdf_text(pdf.content)


def test_removing_system_cost_clears_stale_financials(client, project_payload):
    project_id = _calculated_project(client, project_payload)

    # PUT is a full replace; an explicit null is the same as omitting the field.
    client.put(f"/api/projects/{project_id}", json={**project_payload, "system_cost_inr": None})
    recalculated = client.post(f"/api/projects/{project_id}/calculate").json()

    assert recalculated["system_cost_inr"] is None
    assert recalculated["payback_years"] is None
    assert recalculated["irr_pct"] is None


def test_missing_project_404(client):
    assert client.get("/api/projects/999999").status_code == 404


def test_calculate_rejects_invalid_location(client, project_payload, monkeypatch):
    async def rejecting_fetch(*args):
        raise InvalidLocationError("Location over the sea. Please, select another location")

    monkeypatch.setattr(irradiance, "fetch_pvgis", rejecting_fetch)
    # A cell no other test caches, so the lookup reaches the (rejecting) fetch.
    created = client.post("/api/projects/", json={**project_payload, "latitude": 0.0, "longitude": -30.0})

    response = client.post(f"/api/projects/{created.json()['id']}/calculate")

    assert response.status_code == 422
    assert "over the sea" in response.json()["detail"]


@pytest.mark.parametrize("field, value", [
    ("inverter_replacement_year", 30),
    ("inverter_replacement_cost_inr", -1),
    ("tilt_deg", 120),
    ("azimuth_deg", 270),
    ("irradiance_calibration", 83),  # a typo for 0.83
    ("latitude", 95),
    ("system_cost_inr", -5),
    ("subsidy_inr", -1),
    ("tariff_inr_per_kwh", 0),
    ("export_ratio_pct", 150),
    ("discount_rate_pct", 45),
])
def test_out_of_range_inputs_rejected(client, project_payload, field, value):
    assert client.post("/api/projects/", json={**project_payload, field: value}).status_code == 422


def test_pdf_requires_calculation(client, project_payload):
    created = client.post("/api/projects/", json=project_payload)
    project_id = created.json()["id"]
    assert client.get(f"/api/projects/{project_id}/report/pdf").status_code == 400


def test_pdf_streams_then_deletes_temp_file(client, project_payload):
    project_id = _calculated_project(client, project_payload)
    before = set(glob.glob("./temp_pdfs/*.pdf"))

    response = client.get(f"/api/projects/{project_id}/report/pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    # The BackgroundTask must remove the file once the response is streamed.
    assert set(glob.glob("./temp_pdfs/*.pdf")) - before == set()


def test_pdf_filename_is_sanitised(client, project_payload):
    project_payload["project_name"] = '<img src=x onerror=alert(1)>/../../etc/passwd'
    project_id = _calculated_project(client, project_payload)

    response = client.get(f"/api/projects/{project_id}/report/pdf")

    assert response.status_code == 200
    # Strip the quotes Starlette wraps the filename in before inspecting it.
    filename = response.headers["content-disposition"].split("filename=")[-1].strip('"')
    assert not set('<>/\\"\r\n') & set(filename), filename


def test_pdf_has_financial_page(client, project_payload):
    project_id = _calculated_project(client, project_payload)

    text = _pdf_text(client.get(f"/api/projects/{project_id}/report/pdf").content)

    assert "FINANCIAL SUMMARY" in text
    assert "Subsidy (PM Surya Ghar)" in text
    assert "Rs. 78,000" in text
    assert "CO2 Baseline Database v21.0" in text


@pytest.mark.parametrize("amount, expected", [
    (0, "Rs. 0"),
    (999, "Rs. 999"),
    (100_000, "Rs. 1,00,000"),
    (445_875, "Rs. 4,45,875"),
    (1_234_567, "Rs. 12,34,567"),
    (-364_369, "-Rs. 3,64,369"),
    (523_874.6, "Rs. 5,23,875"),
])
def test_format_inr_uses_lakh_grouping(amount, expected):
    assert format_inr(amount) == expected


# --- search, ordering, update, delete (Phase 3) ------------------------------

def test_search_matches_project_or_client_name(client, project_payload):
    client.post("/api/projects/", json={**project_payload, "project_name": "Zebra Rooftop", "client_name": "Ms. Iyer"})
    client.post("/api/projects/", json={**project_payload, "project_name": "Quokka Villa", "client_name": "Mr. Bose"})

    by_project = client.get("/api/projects/", params={"search": "zebra"}).json()
    by_client = client.get("/api/projects/", params={"search": "bose"}).json()

    # Case-insensitive, and matches either column.
    assert [p["project_name"] for p in by_project] == ["Zebra Rooftop"]
    assert [p["project_name"] for p in by_client] == ["Quokka Villa"]
    assert client.get("/api/projects/", params={"search": "nothingmatchesthis"}).json() == []


def test_projects_are_newest_first(client, project_payload):
    first = client.post("/api/projects/", json={**project_payload, "project_name": "Older Aardvark"}).json()
    second = client.post("/api/projects/", json={**project_payload, "project_name": "Newer Aardvark"}).json()

    listed = client.get("/api/projects/", params={"search": "Aardvark"}).json()

    assert [p["id"] for p in listed] == [second["id"], first["id"]]


def test_put_is_a_full_replace(client, project_payload):
    project_id = _calculated_project(client, project_payload)
    without_optional = {k: v for k, v in project_payload.items() if k != "system_cost_inr"}

    updated = client.put(f"/api/projects/{project_id}", json=without_optional).json()

    # Omitted optional field is cleared, not carried over.
    assert updated["system_cost_inr"] is None
    # Inputs may have changed, so the stored results are stale until recalculated.
    assert updated["is_calculated"] is False


def test_put_missing_project_404(client, project_payload):
    assert client.put("/api/projects/999999", json=project_payload).status_code == 404


def test_delete_removes_the_project(client, project_payload):
    project_id = _calculated_project(client, project_payload)

    assert client.delete(f"/api/projects/{project_id}").status_code == 204
    assert client.get(f"/api/projects/{project_id}").status_code == 404
    assert client.delete(f"/api/projects/{project_id}").status_code == 404


def test_pdf_has_page_numbers_and_monthly_generation(client, project_payload):
    project_id = _calculated_project(client, project_payload)

    text = _pdf_text(client.get(f"/api/projects/{project_id}/report/pdf").content)

    assert "MONTHLY GENERATION" in text
    assert "Page 1" in text and "Page 4" in text
    # Every month label appears in the chart axis and the table.
    for month in ("Jan", "Jun", "Dec"):
        assert month in text


# --- geometry-derived shading (Phase 4) --------------------------------------

def test_shading_auto_off_uses_the_operator_value_and_skips_overpass(client, project_payload, offline_overpass):
    project_id = _calculated_project(client, {**project_payload, "shading_loss_pct": 1.5})

    fetched = client.get(f"/api/projects/{project_id}").json()

    assert fetched["shading_loss_pct"] == 1.5
    assert fetched["shading_computed_pct"] is None
    # Off by default means no call to a free public service.
    assert offline_overpass == []


def test_shading_auto_replaces_the_operator_value(client, project_payload):
    project_id = _calculated_project(client, {**project_payload, "shading_loss_pct": 0.0, "shading_auto": True})

    fetched = client.get(f"/api/projects/{project_id}").json()

    assert fetched["shading_computed_pct"] > 0
    assert fetched["shading_loss_pct"] == fetched["shading_computed_pct"]
    assert fetched["shading_neighbour_count"] > 0
    # The reference neighbourhood has no height tags at all; the report must say so.
    assert fetched["shading_heights_assumed"] == fetched["shading_neighbour_count"]
    assert json.loads(fetched["shading_monthly_json"])[11] > json.loads(fetched["shading_monthly_json"])[5]


def test_shading_feeds_the_loss_stack_and_lowers_generation(client, project_payload):
    plain = _calculated_project(client, {**project_payload, "shading_loss_pct": 0.0})
    shaded = _calculated_project(client, {**project_payload, "shading_loss_pct": 0.0, "shading_auto": True})

    plain_project = client.get(f"/api/projects/{plain}").json()
    shaded_project = client.get(f"/api/projects/{shaded}").json()

    assert shaded_project["total_system_loss"] > plain_project["total_system_loss"]
    assert shaded_project["performance_ratio"] < plain_project["performance_ratio"]
    assert shaded_project["annual_gen_kwh"] < plain_project["annual_gen_kwh"]


def test_shading_falls_back_to_the_operator_value_when_overpass_is_down(client, project_payload, monkeypatch):
    async def failing_fetch(*args):
        raise httpx.ConnectError("overpass unreachable")

    monkeypatch.setattr(buildings, "fetch_buildings", failing_fetch)
    project_id = _calculated_project(client, {
        **project_payload, "shading_loss_pct": 2.0, "shading_auto": True,
        "latitude": 12.9716, "longitude": 77.5946,  # an uncached cell
    })

    fetched = client.get(f"/api/projects/{project_id}").json()

    # The proposal still calculates; no geometry means no invented skyline.
    assert fetched["is_calculated"] is True
    assert fetched["shading_computed_pct"] is None
    assert fetched["shading_loss_pct"] == 2.0


def test_pdf_states_the_shading_basis(client, project_payload):
    project_id = _calculated_project(client, {**project_payload, "shading_auto": True})

    text = _pdf_text(client.get(f"/api/projects/{project_id}/report/pdf").content)

    assert "estimated from the geometry" in text
    assert "assumed at 6 m" in text


def test_inverter_replacement_is_applied_and_reported(client, project_payload):
    project_id = _calculated_project(client, project_payload)
    fetched = client.get(f"/api/projects/{project_id}").json()

    # On by default: leaving a known mid-life cost out overstates lifetime savings.
    assert fetched["inverter_replacement_applied_inr"] == round(project_payload["system_cost_inr"] * 0.12)
    assert json.loads(fetched["cashflow_json"])[11]["replacement_inr"] > 0

    text = _pdf_text(client.get(f"/api/projects/{project_id}/report/pdf").content)
    assert "Inverter Replacement (year 12)" in text


def test_inverter_replacement_can_be_switched_off(client, project_payload):
    off = _calculated_project(client, {**project_payload, "inverter_replacement_year": 0})
    on = _calculated_project(client, project_payload)

    off_project = client.get(f"/api/projects/{off}").json()
    on_project = client.get(f"/api/projects/{on}").json()

    assert off_project["inverter_replacement_applied_inr"] is None
    assert off_project["lifetime_net_savings_inr"] > on_project["lifetime_net_savings_inr"]


def test_pdf_cashflow_shows_the_replacement_year(client, project_payload):
    project_id = _calculated_project(client, {**project_payload, "inverter_replacement_year": 11})
    text = _pdf_text(client.get(f"/api/projects/{project_id}/report/pdf").content)
    # Year 11 is not a normal milestone row; it appears because the cost lands there.
    assert "Inverter Replacement (year 11)" in text


# --- P90, site temperature loss, shaded months (Phase 7) --------------------

def test_p90_is_reported_alongside_p50(client, project_payload):
    project_id = _calculated_project(client, project_payload)
    fetched = client.get(f"/api/projects/{project_id}").json()

    assert fetched["annual_gen_p90_kwh"] < fetched["annual_gen_kwh"]
    assert fetched["annual_gen_p90_kwh"] / fetched["annual_gen_kwh"] == pytest.approx(0.977, abs=0.01)


def test_temperature_loss_auto_uses_the_site_figure(client, project_payload):
    manual = _calculated_project(client, {**project_payload, "temp_loss_pct": 11.5})
    auto = _calculated_project(client, {**project_payload, "temp_loss_pct": 11.5, "temp_loss_auto": True})

    manual_project = client.get(f"/api/projects/{manual}").json()
    auto_project = client.get(f"/api/projects/{auto}").json()

    # Off by default, so the operator's figure stands.
    assert manual_project["temp_loss_pct"] == 11.5
    # PVGIS reports ~10.98% for free-standing mounting at this site.
    assert auto_project["temp_loss_pct"] == pytest.approx(10.98, abs=0.05)
    assert auto_project["performance_ratio"] > manual_project["performance_ratio"]


def test_the_computed_temperature_loss_is_always_reported(client, project_payload):
    # Shown even when not applied, so the operator can see what the site suggests.
    project_id = _calculated_project(client, project_payload)
    fetched = client.get(f"/api/projects/{project_id}").json()

    assert fetched["temp_loss_computed_pct"] == pytest.approx(10.98, abs=0.05)
    assert fetched["temp_loss_pct"] == project_payload.get("temp_loss_pct", 11.5)


def test_flush_mounting_runs_hotter_than_elevated_racking(client, project_payload):
    elevated = _calculated_project(client, {**project_payload, "temp_loss_auto": True, "mounting_type": "free"})
    flush = _calculated_project(client, {**project_payload, "temp_loss_auto": True, "mounting_type": "building"})

    elevated_project = client.get(f"/api/projects/{elevated}").json()
    flush_project = client.get(f"/api/projects/{flush}").json()

    assert flush_project["temp_loss_pct"] > elevated_project["temp_loss_pct"]
    assert flush_project["annual_gen_kwh"] < elevated_project["annual_gen_kwh"]
    # Same sunlight either way: only the module temperature differs.
    assert flush_project["irradiance_h_annual"] == pytest.approx(
        elevated_project["irradiance_h_annual"], abs=0.2
    )


def test_an_unknown_mounting_is_rejected(client, project_payload):
    assert client.post("/api/projects/", json={**project_payload, "mounting_type": "floating"}).status_code == 422


def test_shading_reshapes_the_monthly_split(client, project_payload):
    plain = _calculated_project(client, {**project_payload, "shading_loss_pct": 0.0})
    shaded = _calculated_project(client, {**project_payload, "shading_loss_pct": 0.0, "shading_auto": True})

    plain_months = json.loads(client.get(f"/api/projects/{plain}").json()["monthly_gen_json"])
    shaded_project = client.get(f"/api/projects/{shaded}").json()
    shaded_months = json.loads(shaded_project["monthly_gen_json"])

    december_share_plain = plain_months[11]["value_kwh"] / sum(m["value_kwh"] for m in plain_months)
    december_share_shaded = shaded_months[11]["value_kwh"] / sum(m["value_kwh"] for m in shaded_months)

    # December is the most shaded month at the reference site, so it loses share.
    assert december_share_shaded < december_share_plain
    # The months still add up to the year.
    assert sum(m["value_kwh"] for m in shaded_months) == pytest.approx(
        shaded_project["annual_gen_kwh"], abs=1.0
    )


def test_pdf_shows_p90_with_its_caveat(client, project_payload):
    project_id = _calculated_project(client, {**project_payload, "mounting_type": "building"})

    text = _pdf_text(client.get(f"/api/projects/{project_id}/report/pdf").content)

    assert "P90:" in text
    assert "exceeded in 9 years out of 10" in text
    # Never presented as bankable: this is weather variability only.
    assert "not a bankable" in text
    assert "flush mounted" in text
