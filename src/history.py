"""Append-only record of every value the dashboard has seen.

data/history/vintages.csv   one row per (series, period) the first time a value
                            is seen and again each time the source revises it,
                            stamped with the retrieval date. Nothing is ever
                            deleted, so any past view of the data can be rebuilt.
data/history/refresh_log.csv one row per series per refresh run (status, latest
                            period and value), for an audit trail of the feed.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT / "data" / "history"
VINTAGES = HISTORY_DIR / "vintages.csv"
REFRESH_LOG = HISTORY_DIR / "refresh_log.csv"
VINTAGE_COLS = ["retrieved", "series", "period", "value", "change"]
LOG_COLS = ["retrieved", "series", "status", "observations", "latest_period", "latest_value", "detail"]
TOL = 1e-9


def _read(path: Path, cols: list[str]) -> pd.DataFrame:
    if path.exists() and path.stat().st_size:
        return pd.read_csv(path, dtype={"series": str, "change": str, "status": str})
    return pd.DataFrame(columns=cols)


def load_vintages() -> pd.DataFrame:
    df = _read(VINTAGES, VINTAGE_COLS)
    if len(df):
        df["retrieved"] = pd.to_datetime(df["retrieved"])
        df["period"] = pd.to_datetime(df["period"])
        df["value"] = df["value"].astype(float)
    return df


def latest_known(vintages: pd.DataFrame) -> dict[tuple[str, pd.Timestamp], float]:
    if vintages.empty:
        return {}
    last = vintages.sort_values("retrieved").groupby(["series", "period"], as_index=False).last()
    return {(r.series, r.period): float(r.value) for r in last.itertuples(index=False)}


def new_rows(series: dict[str, pd.Series], known: dict, retrieved: pd.Timestamp) -> pd.DataFrame:
    """Rows for values never seen before ('new') or that differ from the last seen ('revised')."""
    rows = []
    for key, s in series.items():
        for period, value in s.dropna().items():
            period = pd.Timestamp(period)
            prev = known.get((key, period))
            if prev is None:
                rows.append((retrieved, key, period, float(value), "new"))
            elif abs(prev - float(value)) > TOL:
                rows.append((retrieved, key, period, float(value), "revised"))
    return pd.DataFrame(rows, columns=VINTAGE_COLS)


def _append(path: Path, df: pd.DataFrame, cols: list[str]) -> None:
    if df.empty:
        return
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    out = df[cols].copy()
    for c in ("retrieved", "period", "latest_period"):
        if c in out.columns:
            out[c] = pd.to_datetime(out[c]).dt.strftime("%Y-%m-%d")
    out.to_csv(path, mode="a", header=not path.exists() or path.stat().st_size == 0, index=False)


def record(series: dict[str, pd.Series], errors: dict[str, str], retrieved: pd.Timestamp | None = None) -> dict:
    """Append new/revised values and a log row per series. Returns counts."""
    retrieved = pd.Timestamp(retrieved or pd.Timestamp.now(tz="Australia/Sydney").date())
    added = new_rows(series, latest_known(load_vintages()), retrieved)
    _append(VINTAGES, added, VINTAGE_COLS)

    log = []
    for key, s in series.items():
        s = s.dropna()
        log.append((retrieved, key, "ok", len(s), s.index[-1] if len(s) else pd.NaT,
                    float(s.iloc[-1]) if len(s) else None, ""))
    for key, err in errors.items():
        log.append((retrieved, key, "failed", 0, pd.NaT, None, err[:200]))
    _append(REFRESH_LOG, pd.DataFrame(log, columns=LOG_COLS), LOG_COLS)
    return {
        "new": int((added["change"] == "new").sum()) if len(added) else 0,
        "revised": int((added["change"] == "revised").sum()) if len(added) else 0,
    }


def as_of(key: str, date, vintages: pd.DataFrame | None = None) -> pd.Series:
    """The series as it looked on `date`: the last value retrieved on or before it, per period.

    Use this for point-in-time (real-time) analysis, e.g. what a credit model
    would have seen before later revisions.
    """
    v = load_vintages() if vintages is None else vintages
    v = v[(v["series"] == key) & (v["retrieved"] <= pd.Timestamp(date))]
    if v.empty:
        return pd.Series(dtype=float, name=key)
    s = v.sort_values("retrieved").groupby("period")["value"].last()
    s.name = key
    return s


def revisions(key: str | None = None, vintages: pd.DataFrame | None = None) -> pd.DataFrame:
    """Every revision: series, period, old value, new value, date seen."""
    v = load_vintages() if vintages is None else vintages
    if key:
        v = v[v["series"] == key]
    v = v.sort_values(["series", "period", "retrieved"]).copy()
    v["previous"] = v.groupby(["series", "period"])["value"].shift()
    return v[v["change"] == "revised"][["retrieved", "series", "period", "previous", "value"]]
