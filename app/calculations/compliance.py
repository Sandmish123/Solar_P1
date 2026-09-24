"""Indian rooftop compliance checks for a chosen module and inverter.

Pure functions, no DB or IO, like `solar.py` and `financial.py`. The panel and inverter
arguments are duck-typed, so this module never imports the ORM.

Two rules are asserted, both sourced:

- **ALMM List-I** (approved modules) is required for net-metered and PM Surya Ghar
  projects.
- **DCR** (domestic content) is required for subsidy-linked projects, evidenced by a
  16-digit traceability certificate. Mixing DCR and non-DCR stock fails inspection.

No inverter rule is asserted. ALMM List-I covers modules, and nothing inverter-side was
verified against a primary source, so `bis_certified` is carried as information only.

**Unknown never passes.** The catalog's compliance flags are tri-state, and a module
whose status was never recorded blocks the subsidy exactly as a non-compliant one does:
a subsidy you cannot evidence is one the customer will not receive.
"""
from dataclasses import dataclass
from datetime import date

# MNRE extended a blanket List-II (domestic cell) exemption for net-metering and open
# access projects to this date. What replaces it is not yet published, so this only ever
# raises a warning - hard-blocking on a guess about a future rule would be worse.
ALMM_LIST_II_EXEMPTION_ENDS = date(2026, 12, 31)


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str  # "error" | "warning"
    message: str


# An error with any of these means the customer cannot evidence the subsidy, so it is
# not applied to the financials at all. Showing a payback built on money that will not
# arrive is the failure this phase exists to prevent.
SUBSIDY_BLOCKING_CODES = frozenset({
    "almm_not_listed",
    "almm_unknown",
    "dcr_not_compliant",
    "dcr_unknown",
})


def check_compliance(panel, inverter=None, claiming_subsidy: bool = False, today: date = None) -> list:
    """Issues for a project's chosen components. Empty list means nothing to report.

    `panel` may be None for a project that predates the catalog; nothing is asserted
    about components that were never selected.
    """
    if panel is None:
        return []

    today = today or date.today()
    issues = []
    label = f"{panel.manufacturer} {panel.model}"

    # ALMM List-I: required for net metering and for PM Surya Ghar.
    if panel.almm_listed is None:
        issues.append(Issue(
            "almm_unknown", "error",
            f"ALMM status is not recorded for {label}. Confirm it against the MNRE "
            f"ALMM List-I and set it on the component before quoting.",
        ))
    elif not panel.almm_listed:
        issues.append(Issue(
            "almm_not_listed", "error",
            f"{label} is not on ALMM List-I. Net-metered and PM Surya Ghar projects "
            f"require a listed module.",
        ))

    # DCR: only relevant when a subsidy is being claimed.
    if claiming_subsidy:
        if panel.dcr is None:
            issues.append(Issue(
                "dcr_unknown", "error",
                f"DCR status is not recorded for {label}. Subsidy projects need a "
                f"DCR module with a 16-digit traceability certificate.",
            ))
        elif not panel.dcr:
            issues.append(Issue(
                "dcr_not_compliant", "error",
                f"{label} is not DCR compliant, so this system is not eligible for the "
                f"PM Surya Ghar subsidy. Mixing DCR and non-DCR stock fails inspection.",
            ))

    # List-II: a dated heads-up rather than a rule, because the successor is unpublished.
    if today <= ALMM_LIST_II_EXEMPTION_ENDS:
        issues.append(Issue(
            "almm_list_ii_exemption_ending", "warning",
            f"The ALMM List-II (domestic cell) exemption for net-metered projects ends "
            f"on {ALMM_LIST_II_EXEMPTION_ENDS:%d %b %Y}. Check the current rule for "
            f"commissioning dates after that.",
        ))
    else:
        issues.append(Issue(
            "almm_list_ii_exemption_ended", "warning",
            f"The ALMM List-II exemption ended on {ALMM_LIST_II_EXEMPTION_ENDS:%d %b %Y}. "
            f"Confirm the cell-sourcing rule that now applies before commissioning.",
        ))

    # Datasheet completeness: not a compliance matter, but the same panel warrants it.
    for component, kind in ((panel, "module"), (inverter, "inverter")):
        if component is not None and not component.datasheet_verified:
            issues.append(Issue(
                "datasheet_unverified", "warning",
                f"Datasheet values for the {kind} {component.manufacturer} "
                f"{component.model} have not been verified against the manufacturer's "
                f"sheet.",
            ))

    return issues


def blocks_subsidy(issues: list) -> bool:
    return any(issue.code in SUBSIDY_BLOCKING_CODES for issue in issues)


def has_errors(issues: list) -> bool:
    return any(issue.severity == "error" for issue in issues)


def to_dicts(issues: list) -> list:
    return [{"code": i.code, "severity": i.severity, "message": i.message} for i in issues]
