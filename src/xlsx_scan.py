"""Find labelled time series inside messy statistical Excel workbooks.

Agency workbooks (APRA, ASIC) move cells around between releases, so instead
of fixed cell addresses we search by meaning: a header row (or column) full of
dates, and a row (or column) whose label matches a regex. Both orientations
are handled:

  dates across:   | label            | Mar 2026 | Jun 2026 |      dates down:  | Quarter  | Total |
                  | Non-performing   |   1.0    |   1.1    |                   | Mar 2026 |  560  |
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
from openpyxl import load_workbook

MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
_TEXT_DATE = re.compile(rf"^\s*({MONTHS})[a-z]*\.?[\s\-/']*(qtr|quarter)?[\s\-/']*'?(\d{{2}}|\d{{4}})\b", re.I)
_ISO_DATE = re.compile(r"^\s*(\d{4})[-/](\d{1,2})")
MAX_ROWS, MAX_COLS = 600, 400


def to_period(v) -> pd.Timestamp | None:
    """Month-end timestamp for a date-like cell, else None."""
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(v).to_period("M").to_timestamp(how="end").normalize()
    if isinstance(v, str):
        s = v.strip()
        m = _TEXT_DATE.match(s)
        if m:
            year = int(m.group(3))
            year += 2000 if year < 100 else 0
            month = MONTHS.split("|").index(m.group(1).lower()[:3]) + 1
            return pd.Timestamp(year, month, 1).to_period("M").to_timestamp(how="end").normalize()
        m = _ISO_DATE.match(s)
        if m and 1 <= int(m.group(2)) <= 12:
            return pd.Timestamp(int(m.group(1)), int(m.group(2)), 1).to_period("M").to_timestamp(how="end").normalize()
    return None


def to_number(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "").rstrip("%")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


@dataclass
class Match:
    sheet: str
    label: str
    orientation: str  # "across" or "down"
    series: pd.Series


def load_sheets(content: bytes, sheet_pattern: str | None = None, max_rows: int = MAX_ROWS) -> dict[str, list[list]]:
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    out = {}
    pat = re.compile(sheet_pattern, re.I) if sheet_pattern else None
    for ws in wb.worksheets:
        if pat and not pat.search(ws.title):
            continue
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= max_rows:
                break
            rows.append(list(row[:MAX_COLS]))
        out[ws.title] = rows
    wb.close()
    return out


def _cell(rows, r, c):
    return rows[r][c] if r < len(rows) and c < len(rows[r]) else None


def find_series(sheets: dict[str, list[list]], label_pattern: str, min_points: int = 3) -> list[Match]:
    """Every series whose label matches label_pattern, in either orientation."""
    pat = re.compile(label_pattern, re.I)
    found: list[Match] = []
    for name, rows in sheets.items():
        # dates across: header rows with >= 4 date cells
        headers = {}
        for r, row in enumerate(rows):
            cols = {c: to_period(v) for c, v in enumerate(row)}
            cols = {c: d for c, d in cols.items() if d is not None}
            if len(cols) >= 4:
                headers[r] = cols
        for r, row in enumerate(rows):
            above = [h for h in headers if h < r]
            if not above:
                continue
            hcols = headers[max(above)]
            first_date_col = min(hcols)
            label = " ".join(_text(v) for v in row[:max(first_date_col, 1)] if _text(v))
            if not label or not pat.search(label):
                continue
            pts = {d: to_number(_cell(rows, r, c)) for c, d in hcols.items()}
            s = pd.Series({d: v for d, v in pts.items() if v is not None}, dtype=float).sort_index()
            s = s[~s.index.duplicated(keep="last")]
            if len(s) >= min_points:
                found.append(Match(name, label, "across", s))
        # dates down: a column with >= 4 date cells; labels in the rows above
        ncols = max((len(r) for r in rows), default=0)
        for c in range(min(ncols, MAX_COLS)):
            drows = {r: to_period(_cell(rows, r, c)) for r in range(len(rows))}
            drows = {r: d for r, d in drows.items() if d is not None}
            if len(drows) < 4:
                continue
            first = min(drows)
            for c2 in range(c + 1, min(ncols, MAX_COLS)):
                label = " ".join(_text(_cell(rows, r, c2)) for r in range(max(0, first - 4), first) if _text(_cell(rows, r, c2)))
                if not label or not pat.search(label):
                    continue
                pts = {d: to_number(_cell(rows, r, c2)) for r, d in drows.items()}
                s = pd.Series({d: v for d, v in pts.items() if v is not None}, dtype=float).sort_index()
                s = s[~s.index.duplicated(keep="last")]
                if len(s) >= min_points:
                    found.append(Match(name, label, "down", s))
            break  # only the first date column per sheet
    return found


def describe(sheets: dict[str, list[list]], keywords: str, max_lines: int = 40) -> str:
    """Plain-text map of a workbook: sheets, sizes, first rows, keyword rows."""
    kw = re.compile(keywords, re.I)
    lines = []
    for name, rows in sheets.items():
        width = max((len(r) for r in rows), default=0)
        lines.append(f"### Sheet `{name}` ({len(rows)} rows read, {width} cols)")
        shown = 0
        for r, row in enumerate(rows):
            cells = [str(v)[:28] for v in row[:14] if v not in (None, "")]
            if not cells:
                continue
            if r < 12 or any(kw.search(str(v)) for v in row[:6] if isinstance(v, str)):
                tail = [str(v)[:12] for v in row[-3:] if v not in (None, "")] if len(row) > 14 else []
                lines.append(f"- r{r}: " + " | ".join(cells) + (f" ... {' | '.join(tail)}" if tail else ""))
                shown += 1
            if shown >= max_lines:
                lines.append("- ...")
                break
        lines.append("")
    return "\n".join(lines)
