"""Load dashboard data: live RBA tables first, bundled snapshot as fallback."""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .rba import fetch_table, select_series
from .specs import LIVE_SERIES

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "data" / "snapshot"
MANUAL_DIR = ROOT / "data" / "manual"
HISTORY_START = pd.Timestamp("2015-01-01")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", str(6 * 3600)))


@dataclass
class DashboardData:
    series: dict[str, pd.Series] = field(default_factory=dict)
    origin: dict[str, str] = field(default_factory=dict)  # key -> "live" | "snapshot"
    errors: dict[str, str] = field(default_factory=dict)
    home_values: pd.DataFrame | None = None
    stress: pd.DataFrame | None = None
    loaded_at: pd.Timestamp | None = None


def live_enabled() -> bool:
    return os.getenv("LIVE_DATA", "1").lower() not in ("0", "false", "no")


def fetch_live() -> tuple[dict[str, pd.Series], dict[str, str]]:
    """Fetch every live series, one download per RBA table."""
    by_table = defaultdict(list)
    for spec in LIVE_SERIES:
        by_table[spec.table].append(spec)
    out: dict[str, pd.Series] = {}
    errors: dict[str, str] = {}
    for table, specs in by_table.items():
        try:
            tbl = fetch_table(table)
        except Exception as exc:  # network, HTTP or parse failure
            for spec in specs:
                errors[spec.key] = f"table {table}: {exc.__class__.__name__}: {exc}"
            continue
        for spec in specs:
            try:
                s = select_series(tbl, spec)
                out[spec.key] = s[s.index >= HISTORY_START]
            except KeyError as exc:
                errors[spec.key] = str(exc)
    return out, errors


def load_snapshot(key: str) -> pd.Series | None:
    path = SNAPSHOT_DIR / f"{key}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    s = df.set_index("date")["value"].astype(float).sort_index()
    s.name = key
    return s


def save_snapshot(series: dict[str, pd.Series]) -> list[Path]:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for key, s in series.items():
        path = SNAPSHOT_DIR / f"{key}.csv"
        pd.DataFrame({"date": s.index.strftime("%Y-%m-%d"), "value": s.values}).to_csv(path, index=False)
        written.append(path)
    return written


def load_manual() -> tuple[pd.DataFrame, pd.DataFrame]:
    home = pd.read_csv(MANUAL_DIR / "home_values.csv", parse_dates=["date"]).sort_values("date")
    stress = pd.read_csv(MANUAL_DIR / "stress_indicators.csv")
    return home, stress


def build(use_live: bool | None = None) -> DashboardData:
    use_live = live_enabled() if use_live is None else use_live
    data = DashboardData()
    live, errors = fetch_live() if use_live else ({}, {})
    data.errors = errors
    for spec in LIVE_SERIES:
        if spec.key in live and not live[spec.key].empty:
            data.series[spec.key] = live[spec.key]
            data.origin[spec.key] = "live"
            continue
        snap = load_snapshot(spec.key)
        if snap is not None and not snap.empty:
            data.series[spec.key] = snap
            data.origin[spec.key] = "snapshot"
        if use_live and spec.key in errors:
            log.warning("Live fetch failed for %s: %s", spec.key, errors[spec.key])
    data.home_values, data.stress = load_manual()
    data.loaded_at = pd.Timestamp.now(tz="Australia/Sydney")
    return data


_cache: dict[str, object] = {"data": None, "at": 0.0}
_lock = threading.Lock()


def get_data() -> DashboardData:
    """Cached loader: refetches at most once per CACHE_TTL_SECONDS."""
    with _lock:
        now = time.time()
        if _cache["data"] is None or now - float(_cache["at"]) > CACHE_TTL_SECONDS:
            _cache["data"] = build()
            _cache["at"] = now
        return _cache["data"]  # type: ignore[return-value]
