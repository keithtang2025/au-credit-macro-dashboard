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

def apra_npl_from_sheets(sheets: dict) -> tuple[pd.Series, str]:
    sheets = {k: v for k, v in sheets.items() if not SKIP_SHEETS.search(k)}
    ratio = [m for m in find_series(sheets, r"non[- ]?performing.*(%|share|per ?cent|proportion|ratio)|"
                                            r"(%|share|proportion).*non[- ]?performing")
             if m.series.between(0, 10).all()]
    best = _prefer_total(ratio)
    if best is not None:
        return best.series, f"ratio row '{best.label}' in sheet '{best.sheet}' ({best.orientation})"
    nums = [m for m in find_series(sheets, r"^\s*non[- ]?performing") if "commercial" not in m.label.lower()]
    dens = find_series(sheets, r"^\s*(total )?credit outstanding|^\s*total (housing )?credit")
    for num in sorted(nums, key=lambda m: -len(m.series)):
        same = [d for d in dens if d.sheet == num.sheet and d.orientation == num.orientation]
        den = _prefer_total(same)
        if den is None:
            continue
        share = (num.series / den.series * 100).dropna()
        share = share[(share > 0) & (share < 10)]
        if len(share) >= 3:
            return share, (f"'{num.label}' / '{den.label}' x100 in sheet '{num.sheet}' ({num.orientation})")
    raise LookupError("APRA: no non-performing housing loan series found")


def fetch_apra() -> tuple[dict[str, pd.Series], str]:
    html = _get(APRA_PAGE).text
    url = find_link(html, APRA_PAGE, r"property exposures statistics", exclude=r"historical")
    sheets = load_sheets(_get(url).content)
    lines = [f"Workbook: {url}", f"Sheets: {', '.join(sheets)}"]
    try:
        s, how = apra_npl_from_sheets(sheets)
        s.name = "apra_housing_npl"
        lines.append(f"apra_housing_npl: {how}; {len(s)} obs, latest {s.index[-1]:%Y-%m} = {s.iloc[-1]:.3f}")
        return {"apra_housing_npl": s}, "\n".join(lines)
    except LookupError as exc:
        lines += [f"FAILED: {exc}", "", describe(sheets, r"perform|past due|arrear|outstanding|total")]
        raise LookupError("\n".join(lines)) from exc


# ---------------- ASIC: companies entering external administration (Series 1)

def asic_from_sheets(sheets: dict) -> tuple[pd.Series, str]:
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
AGENCY_KEYS = {"apra_housing_npl", "asic_insolvencies", "asic_insolvencies_12m"}


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
