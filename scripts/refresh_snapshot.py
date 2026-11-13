"""Fetch live RBA/ABS series and overwrite data/snapshot/*.csv.

Run by the scheduled GitHub Action so the bundled fallback stays fresh.
Exits non-zero only if every series failed, so one renamed series does not
block the others from updating.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import fetch_live, save_snapshot  # noqa: E402
from src.specs import LIVE_SERIES  # noqa: E402


def main() -> int:
    series, errors = fetch_live()
    for path in save_snapshot(series):
        print(f"updated {path.name}")
    for key, err in errors.items():
        print(f"FAILED {key}: {err}", file=sys.stderr)
    print(f"{len(series)} of {len(LIVE_SERIES)} series refreshed")
    return 0 if series else 1


if __name__ == "__main__":
    raise SystemExit(main())
