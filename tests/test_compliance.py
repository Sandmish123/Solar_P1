from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.calculations.compliance import (
    ALMM_LIST_II_EXEMPTION_ENDS,
    blocks_subsidy,
    check_compliance,
    has_errors,
    to_dicts,
)

BEFORE_EXPIRY = ALMM_LIST_II_EXEMPTION_ENDS - timedelta(days=30)
AFTER_EXPIRY = ALMM_LIST_II_EXEMPTION_ENDS + timedelta(days=1)


def panel(almm_listed=True, dcr=True, datasheet_verified=True):
    return SimpleNamespace(
        manufacturer="Luminous", model="LUM 635TG132",
        almm_listed=almm_listed, dcr=dcr, datasheet_verified=datasheet_verified,
    )


def inverter(datasheet_verified=True):
    return SimpleNamespace(manufacturer="Luminous", model="NXI 320",
                           datasheet_verified=datasheet_verified)


def codes(issues):
    return {issue.code for issue in issues}


# --- nothing selected ------------------------------------------------------

def test_no_panel_asserts_nothing():
    # Projects that predate the catalog must keep working untouched.
    assert check_compliance(None, None, claiming_subsidy=True, today=BEFORE_EXPIRY) == []


# --- ALMM List-I -----------------------------------------------------------

def test_listed_module_raises_no_almm_error():
    issues = check_compliance(panel(), inverter(), claiming_subsidy=False, today=BEFORE_EXPIRY)
    assert not has_errors(issues)


def test_unlisted_module_is_an_error():
    issues = check_compliance(panel(almm_listed=False), claiming_subsidy=False, today=BEFORE_EXPIRY)
    assert "almm_not_listed" in codes(issues)
    assert has_errors(issues)


def test_unrecorded_almm_status_is_an_error_not_a_pass():
    # Unknown must never read as compliant.
    issues = check_compliance(panel(almm_listed=None), claiming_subsidy=False, today=BEFORE_EXPIRY)
    assert "almm_unknown" in codes(issues)
    assert has_errors(issues)


# --- DCR -------------------------------------------------------------------

def test_dcr_is_only_checked_when_claiming_a_subsidy():
    without = check_compliance(panel(dcr=False), claiming_subsidy=False, today=BEFORE_EXPIRY)
    with_subsidy = check_compliance(panel(dcr=False), claiming_subsidy=True, today=BEFORE_EXPIRY)

    assert "dcr_not_compliant" not in codes(without)
    assert "dcr_not_compliant" in codes(with_subsidy)


@pytest.mark.parametrize("dcr, expected", [(False, "dcr_not_compliant"), (None, "dcr_unknown")])
def test_a_subsidy_needs_a_dcr_module(dcr, expected):
    issues = check_compliance(panel(dcr=dcr), claiming_subsidy=True, today=BEFORE_EXPIRY)
    assert expected in codes(issues)
    assert blocks_subsidy(issues)


def test_a_compliant_module_does_not_block_the_subsidy():
    issues = check_compliance(panel(), inverter(), claiming_subsidy=True, today=BEFORE_EXPIRY)
    assert not blocks_subsidy(issues)
    assert not has_errors(issues)


def test_an_unlisted_module_also_blocks_the_subsidy():
    # PM Surya Ghar requires ALMM List-I as well as DCR.
    issues = check_compliance(panel(almm_listed=False), claiming_subsidy=True, today=BEFORE_EXPIRY)
    assert blocks_subsidy(issues)


# --- List-II exemption date ------------------------------------------------

def test_list_ii_exemption_is_a_warning_before_and_after_expiry():
    before = check_compliance(panel(), claiming_subsidy=False, today=BEFORE_EXPIRY)
    after = check_compliance(panel(), claiming_subsidy=False, today=AFTER_EXPIRY)

    assert "almm_list_ii_exemption_ending" in codes(before)
    assert "almm_list_ii_exemption_ended" in codes(after)
    # Never an error: what replaces the exemption is unpublished, and hard-blocking on
    # a guess about a future rule would be worse than flagging it.
    assert not has_errors(before) and not has_errors(after)
    assert not blocks_subsidy(before) and not blocks_subsidy(after)


# --- datasheet completeness ------------------------------------------------

def test_unverified_datasheets_warn_for_both_components():
    issues = check_compliance(
        panel(datasheet_verified=False), inverter(datasheet_verified=False),
        claiming_subsidy=False, today=BEFORE_EXPIRY,
    )
    warnings = [i for i in issues if i.code == "datasheet_unverified"]
    assert len(warnings) == 2
    assert not has_errors(issues)


def test_to_dicts_is_json_ready():
    payload = to_dicts(check_compliance(panel(almm_listed=False), claiming_subsidy=True, today=BEFORE_EXPIRY))
    assert all(set(item) == {"code", "severity", "message"} for item in payload)
    assert any(item["severity"] == "error" for item in payload)
