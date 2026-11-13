"""Download and parse Reserve Bank of Australia statistical tables (CSV).

RBA tables are published at
https://www.rba.gov.au/statistics/tables/csv/<table>-data.csv
with a block of metadata rows (Title, Description, Frequency, Type, Units,
Source, Publication date, Series ID) followed by dated observations.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

import pandas as pd
import requests

BASE_URL = "https://www.rba.gov.au/statistics/tables/csv/{table}-data.csv"
USER_AGENT = "au-credit-macro-dashboard/1.0 (research dashboard)"
DATE_FORMATS = ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d")


@dataclass(frozen=True)
class SeriesSpec:
    """One series to pull from an RBA table.

    series_id is tried first; if the RBA renames it, title_pattern (a regex
    matched case-insensitively against the Title row) is the fallback.
    """

    key: str
    table: str
    series_id: str
    title_pattern: str
    label: str
    unit: str = "%"


@dataclass
class RbaTable:
    data: pd.DataFrame  # index: dates, columns: series IDs
    titles: dict[str, str]  # series ID -> title
    units: dict[str, str]  # series ID -> units


def _parse_date(value: str):
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return pd.to_datetime(value, format=fmt)
        except (ValueError, TypeError):
            continue
    return None


def parse_rba_csv(text: str) -> RbaTable:
    rows = list(csv.reader(io.StringIO(text)))
    meta: dict[str, list[str]] = {}
    sid_idx = None
    for i, row in enumerate(rows):
        if not row:
            continue
        head = row[0].strip().lower()
        if head in ("title", "units", "series id"):
            meta[head] = [c.strip() for c in row[1:]]
        if head == "series id":
            sid_idx = i
            break
    if sid_idx is None or "series id" not in meta:
        raise ValueError("Not an RBA statistical table: no 'Series ID' row found")

    ids = meta["series id"]
    records = []
    for row in rows[sid_idx + 1 :]:
        if not row or not row[0].strip():
            continue
        d = _parse_date(row[0])
        if d is None:
            continue
        vals = []
        for c in row[1 : len(ids) + 1]:
            c = c.strip().replace(",", "")
            try:
                vals.append(float(c))
            except ValueError:
                vals.append(float("nan"))
        vals += [float("nan")] * (len(ids) - len(vals))
        records.append((d, vals))

    data = pd.DataFrame([v for _, v in records], index=[d for d, _ in records], columns=ids)
    data = data.loc[:, [c for c in data.columns if c]]  # drop blank trailing columns
    data.index.name = "date"
    titles = dict(zip(ids, meta.get("title", [""] * len(ids))))
    units = dict(zip(ids, meta.get("units", [""] * len(ids))))
    return RbaTable(data=data.sort_index(), titles=titles, units=units)


def fetch_table(table: str, timeout: float = 20.0) -> RbaTable:
    url = BASE_URL.format(table=table.lower())
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    raw = resp.content
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return parse_rba_csv(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode RBA table {table}")


def select_series(table: RbaTable, spec: SeriesSpec) -> pd.Series:
    """Return the requested series (NaNs dropped), by ID or by title fallback."""
    col = None
    if spec.series_id in table.data.columns:
        col = spec.series_id
    else:
        pat = re.compile(spec.title_pattern, re.IGNORECASE)
        for sid, title in table.titles.items():
            if sid in table.data.columns and pat.search(title or ""):
                col = sid
                break
    if col is None:
        raise KeyError(f"{spec.key}: series {spec.series_id} not found in RBA table {spec.table}")
    s = table.data[col].dropna()
    s.name = spec.key
    return s
