"""Automated APRA and ASIC series.

Both agencies publish an Excel workbook whose URL changes every release, linked
from a stable page. We read the page, find the newest workbook link, download
it and locate the series by label (see xlsx_scan). Every run also writes a
plain-text report of what was found to data/debug/source_report.md, so layout
changes are easy to diagnose.

These downloads run in the scheduled GitHub Action, not in the web app (the
ASIC workbook is ~17 MB); the app reads the committed snapshot.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urljoin

import pandas as pd
import requests

from .xlsx_scan import Match, describe, find_series, load_sheets

USER_AGENT = "Mozilla/5.0 (compatible; au-credit-macro-dashboard/1.0)"
APRA_PAGE = "https://www.apra.gov.au/quarterly-authorised-deposit-taking-institution-statistics"
ASIC_PAGE = (
    "https://asic.gov.au/regulatory-resources/find-a-document/statistics/insolvency-statistics/"
    "insolvency-statistics-series-1-companies-entering-external-administration/"
)
SKIP_SHEETS = re.compile(r"commercial|explanatory|notes|contents|glossary|cover", re.I)


def _get(url: str, timeout: float = 90.0) -> requests.Response:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r


def find_link(html: str, base: str, pattern: str, exclude: str | None = None) -> str:
    """First .xlsx href whose decoded URL matches pattern (case-insensitive)."""
    pat, exc = re.compile(pattern, re.I), re.compile(exclude, re.I) if exclude else None
    for href in re.findall(r'href="([^"]+\.xlsx?)"', html, flags=re.I):
        decoded = unquote(href)
        if pat.search(decoded) and not (exc and exc.search(decoded)):
            return urljoin(base, href)
    raise LookupError(f"no workbook link matching /{pattern}/ on {base}")


def _prefer_total(matches: list[Match]) -> Match | None:
    if not matches:
        return None

    def score(m: Match):
        lab = m.label.lower()
        return (
            ("total" in lab or "all" in lab) - ("owner" in lab or "invest" in lab or "commercial" in lab) * 2,
            len(m.series),
            m.series.index[-1],
        )

    return max(matches, key=score)


# ---------------- APRA: housing loans non-performing, % of credit outstanding

OUTSTANDING = r"out?standing"  # APRA's Tab 1b label is spelt "Total credit oustanding"

def apra_npl_from_sheets(sheets: dict) -> tuple[pd.Series, str]:
    sheets = {k: v for k, v in sheets.items() if not SKIP_SHEETS.search(k)}
    ratio = [m for m in find_series(sheets, r"non[- ]?performing.*(%|share|per ?cent|proportion|ratio)|"
                                            r"(%|share|proportion).*non[- ]?performing")
             if m.series.between(0, 10).all()]
    best = _prefer_total(ratio)
    if best is not None:
        return best.series, f"ratio row '{best.label}' in sheet '{best.sheet}' ({best.orientation})"
    nums = [m for m in find_series(sheets, r"^\s*non[- ]?performing") if "commercial" not in m.label.lower()]
    dens = find_series(sheets, OUTSTANDING + r"|^\s*total (housing )?credit")
    for num in sorted(nums, key=lambda m: -len(m.series)):
        same = [d for d in dens if d.sheet == num.sheet and d.orientation == num.orientation]
        # NPL share is defined on credit outstanding; limits (incl. redraw) only as a last resort
        outstanding = [d for d in same if re.search(OUTSTANDING, d.label, re.I) and "limit" not in d.label.lower()]
        den = _prefer_total(outstanding or same)
        if den is None:
            continue
        share = (num.series / den.series * 100).dropna()
        share = share[(share > 0) & (share < 10)]
        if len(share) >= 3:
            return share, (f"'{num.label}' / '{den.label}' x100 in sheet '{num.sheet}' ({num.orientation})")
    raise LookupError("APRA: no non-performing housing loan series found")


def apra_pastdue_from_sheets(sheets: dict) -> tuple[pd.Series, str]:
    """Loans 30-89 days past due as % of total credit outstanding (early arrears)."""
    sheets = {k: v for k, v in sheets.items() if not SKIP_SHEETS.search(k)}
    nums = [m for m in find_series(sheets, r"30\s*(-|to|\u2013)\s*89 days past due") if "commercial" not in m.label.lower()]
    for num in sorted(nums, key=lambda m: -len(m.series)):
        dens = [d for d in find_series({num.sheet: sheets[num.sheet]}, OUTSTANDING)
                if d.orientation == num.orientation and "limit" not in d.label.lower()]
        den = _prefer_total(dens)
        if den is None:
            continue
        share = (num.series / den.series * 100).dropna()
        share = share[(share > 0) & (share < 10)]
        if len(share) >= 3:
            return share, f"'{num.label}' / '{den.label}' x100 in sheet '{num.sheet}' ({num.orientation})"
    raise LookupError("APRA: no 30-89 days past due series found")


def fetch_apra() -> tuple[dict[str, pd.Series], str]:
    html = _get(APRA_PAGE).text
    url = find_link(html, APRA_PAGE, r"property exposures statistics", exclude=r"historical")
    sheets = load_sheets(_get(url).content)
    lines = [f"Workbook: {url}", f"Sheets: {', '.join(sheets)}"]
    try:
        s, how = apra_npl_from_sheets(sheets)
        s.name = "apra_housing_npl"
        lines.append(f"apra_housing_npl: {how}; {len(s)} obs, latest {s.index[-1]:%Y-%m} = {s.iloc[-1]:.3f}")
        out = {"apra_housing_npl": s}
        try:
            pd_s, pd_how = apra_pastdue_from_sheets(sheets)
            pd_s.name = "apra_housing_pastdue"
            out["apra_housing_pastdue"] = pd_s
            lines.append(f"apra_housing_pastdue: {pd_how}; {len(pd_s)} obs, latest {pd_s.index[-1]:%Y-%m} = {pd_s.iloc[-1]:.3f}")
        except LookupError as exc:
            lines.append(f"apra_housing_pastdue FAILED: {exc}")
        sheet = re.search(r"in sheet '([^']+)'", how)
        if sheet and sheet.group(1) in sheets:
            lines += ["", describe({sheet.group(1): sheets[sheet.group(1)]}, r"perform|outstanding|limit|total|past due")]
        return out, "\n".join(lines)
    except LookupError as exc:
        lines += [f"FAILED: {exc}", "", describe(sheets, r"perform|past due|arrear|outstanding|total")]
        raise LookupError("\n".join(lines)) from exc


# ---------------- ASIC: companies entering external administration (Series 1)

_FY = re.compile(r"^\s*FY\s?'?(\d{2}|\d{4})\s*$", re.I)
_MONTH_NAMES = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def asic_data_to(sheets: dict) -> pd.Timestamp | None:
    """The 'Data to:' date ASIC prints near the top of the workbook."""
    for rows in sheets.values():
        for row in rows[:8]:
            for i, v in enumerate(row[:-1]):
                if isinstance(v, str) and v.strip().lower().startswith("data to"):
                    nxt = next((x for x in row[i + 1:] if x not in (None, "")), None)
                    try:
                        return pd.Timestamp(nxt).normalize() if nxt is not None else None
                    except (ValueError, TypeError):
                        return None
    return None


def asic_table1(sheets: dict) -> pd.Series:
    """Table 1 layout: month names down the rows, financial years (FY20, FY21...) across.

    FY26 runs July 2025 to June 2026, so July-December belong to the earlier year.
    """
    for name, rows in sheets.items():
        if name.strip() != "1" and not re.match(r"^\s*(table\s*)?1\s*$", name, re.I):
            continue
        for h, row in enumerate(rows):
            fy_cols = {}
            for c, v in enumerate(row):
                m = _FY.match(v) if isinstance(v, str) else None
                if m:
                    y = int(m.group(1))
                    fy_cols[c] = y + 2000 if y < 100 else y
            if len(fy_cols) < 3:
                continue
            label_col = min(fy_cols) - 1
            pts = {}
            for r in range(h + 1, min(h + 40, len(rows))):
                lab = rows[r][label_col] if label_col < len(rows[r]) else None
                if not isinstance(lab, str):
                    continue
                key = lab.strip().lower()[:3]
                if key == "tot":
                    break
                if key not in _MONTH_NAMES:
                    continue
                month = _MONTH_NAMES.index(key) + 1
                for c, fy in fy_cols.items():
                    v = rows[r][c] if c < len(rows[r]) else None
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        year = fy - 1 if month >= 7 else fy
                        pts[pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)] = float(v)
            if len(pts) >= 12:
                return pd.Series(pts, dtype=float).sort_index()
    raise LookupError("ASIC: Table 1 (months x financial years) not found")


def asic_from_sheets(sheets: dict) -> tuple[pd.Series, str]:
    try:
        s = asic_table1(sheets)
        how = "Table 1 (sheet '1'): months x financial-year columns"
        data_to = asic_data_to(sheets)
        if data_to is not None:
            month_end = data_to + pd.offsets.MonthEnd(0)
            s = s[s.index <= month_end]
            if data_to < month_end:  # current month only partly reported
                s = s[s.index < month_end]
                how += f"; partial month after data-to date {data_to:%Y-%m-%d} dropped"
        if len(s) >= 12 and s.tail(12).between(50, 10000).all():
            return s, how
    except LookupError:
        pass
    cands = []
    for m in find_series(sheets, r"^\s*(total|australia|total australia|grand total)\s*$", min_points=12):
        gaps = m.series.index.to_series().diff().dt.days.median()
        if not (20 <= gaps <= 40):  # monthly only
            continue
        if not m.series.tail(12).between(50, 10000).all():
            continue
        name = m.sheet.lower()
        pref = 3 * bool(re.search(r"(^|[^\d])1\.(2|4)\b|series 1\b", name)) - 3 * bool(re.search(r"(^|[^\d])2\.\d|series 2", name))
        cands.append((pref, len(m.series), m))
    if not cands:
        raise LookupError("ASIC: no monthly total series found")
    m = max(cands, key=lambda t: (t[0], t[1]))[2]
    return m.series, f"row/col '{m.label}' in sheet '{m.sheet}' ({m.orientation})"


def rolling_12m(monthly: pd.Series) -> pd.Series:
    s = monthly.asfreq("ME")
    return s.rolling(12, min_periods=12).sum().dropna()


def fetch_asic() -> tuple[dict[str, pd.Series], str]:
    html = _get(ASIC_PAGE).text
    url = find_link(html, ASIC_PAGE, r"series-1-and-series-2")
    sheets = load_sheets(_get(url, timeout=180).content)
    lines = [f"Workbook: {url}", f"Sheets: {', '.join(sheets)}"]
    try:
        s, how = asic_from_sheets(sheets)
        s.name = "asic_insolvencies"
        r12 = rolling_12m(s)
        r12.name = "asic_insolvencies_12m"
        lines.append(f"asic_insolvencies: {how}; {len(s)} obs, latest {s.index[-1]:%Y-%m} = {s.iloc[-1]:.0f}")
        out = {"asic_insolvencies": s}
        if len(r12):
            out["asic_insolvencies_12m"] = r12
        return out, "\n".join(lines)
    except LookupError as exc:
        lines += [f"FAILED: {exc}", "", describe(sheets, r"total|australia|month|series")]
        raise LookupError("\n".join(lines)) from exc


AGENCY_FETCHERS = {"APRA property exposures": fetch_apra, "ASIC insolvency Series 1": fetch_asic}
AGENCY_KEYS = {"apra_housing_npl", "apra_housing_pastdue", "asic_insolvencies", "asic_insolvencies_12m"}


def fetch_agencies() -> tuple[dict[str, pd.Series], dict[str, str], str]:
    series, errors, report = {}, {}, ["# Source report (written by the daily refresh)", ""]
    for name, fn in AGENCY_FETCHERS.items():
        report.append(f"## {name}")
        try:
            got, text = fn()
            series.update(got)
            report.append(text)
        except Exception as exc:  # network, layout or parse failure
            msg = str(exc)
            errors[name] = msg.splitlines()[0] if msg else exc.__class__.__name__
            report.append(f"{exc.__class__.__name__}: {msg}")
        report.append("")
    return series, errors, "\n".join(report)
