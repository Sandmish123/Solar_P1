import base64
import glob
import re
import zlib

import pytest

from app.services import irradiance
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

    # update_project uses exclude_unset: omitting a field leaves it unchanged,
    # an explicit null clears it.
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
