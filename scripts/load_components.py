"""Load the shared component catalog from seeds/components.json.

Idempotent: matches on (org_id NULL, manufacturer, model), inserting what is missing and
updating the fields present in the file. Safe to re-run after editing the seed.

    python scripts/load_components.py [--file seeds/components.json]
"""
import argparse
import json
import sys

sys.path.insert(0, ".")

import app.models  # noqa: E402,F401  (registers every table before mappers configure)
from app.database.session import SessionLocal  # noqa: E402
from app.models.components import InverterModel, PanelModel  # noqa: E402


def _upsert(db, model_class, entry):
    """Shared-catalog rows only: org_id stays NULL so every firm sees them."""
    row = db.query(model_class).filter(
        model_class.org_id.is_(None),
        model_class.manufacturer == entry["manufacturer"],
        model_class.model == entry["model"],
    ).first()

    if row is None:
        db.add(model_class(**entry))
        return "added"

    for field, value in entry.items():
        setattr(row, field, value)
    return "updated"


def main() -> int:
    parser = argparse.ArgumentParser(description="Load the shared component catalog")
    parser.add_argument("--file", default="seeds/components.json")
    args = parser.parse_args()

    with open(args.file) as handle:
        payload = json.load(handle)

    db = SessionLocal()
    try:
        counts = {"added": 0, "updated": 0}
        for key, model_class in (("panels", PanelModel), ("inverters", InverterModel)):
            for entry in payload.get(key, []):
                counts[_upsert(db, model_class, entry)] += 1
        db.commit()
        print(f"Catalog loaded: {counts['added']} added, {counts['updated']} updated.")
        print("Fill in datasheet values and ALMM/DCR status before quoting.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
