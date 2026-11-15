"""Daily refresh: RBA/ABS tables plus APRA and ASIC workbooks.

Run by the scheduled GitHub Action. Updates data/snapshot/*.csv, appends
new and revised values to data/history/, and writes data/debug/source_report.md
describing what was found in the agency workbooks. Exits non-zero only if
every source failed, so one broken source never blocks the others.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agencies import fetch_agencies  # noqa: E402
from src.data import fetch_live, save_snapshot  # noqa: E402
from src.history import record  # noqa: E402
from src.specs import SPEC_BY_KEY  # noqa: E402


def main() -> int:
    series, errors = fetch_live()
    print(f"RBA/ABS: {len(series)} of {len(SPEC_BY_KEY)} series refreshed")

    agency, agency_errors, report = fetch_agencies()
    print(f"APRA/ASIC: {len(agency)} series refreshed ({', '.join(agency) or 'none'})")
    series.update(agency)
    errors.update(agency_errors)

    debug = ROOT / "data" / "debug"
    debug.mkdir(parents=True, exist_ok=True)
    (debug / "source_report.md").write_text(report, encoding="utf-8")

    for path in save_snapshot(series):
        print(f"updated {path.name}")
    for key, err in errors.items():
        print(f"FAILED {key}: {err}", file=sys.stderr)
    counts = record(series, errors)
    print(f"history: {counts['new']} new values, {counts['revised']} revisions archived")
    return 0 if series else 1


if __name__ == "__main__":
    raise SystemExit(main())
