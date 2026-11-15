"""Dashboard content shared by the Dash app (app.py) and the static GitHub Pages build
(scripts/build_static.py): KPI cards, chart cards and the status rows, as plain data."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import charts
from .specs import SPEC_BY_KEY


@dataclass
class Kpi:
    label: str
    value: str
    sub: str


@dataclass
class Card:
    title: str
    note: str
    fig: object
    cid: str


def latest(s: pd.Series | None, fmt: str, signed: bool = False) -> str:
    if s is None or s.empty:
        return "n/a"
    v = float(s.iloc[-1])
    return (f"{v:+{fmt}}" if signed else f"{v:{fmt}}") + "%"


def when(s: pd.Series | None, quarterly: bool = False) -> str:
    if s is None or s.empty:
        return ""
    d = s.index[-1]
    return f"Q{(d.month - 1) // 3 + 1} {d.year}" if quarterly else d.strftime("%b %Y")


def kpis(d) -> list[Kpi]:
    s, hv = d.series, d.home_values
    return [
        Kpi(f"RBA cash rate, {when(s.get('cash_rate'))}", latest(s.get("cash_rate"), ".2f"), "Target rate"),
        Kpi(f"Unemployment, {when(s.get('unemployment'))}", latest(s.get("unemployment"), ".1f"), "Seasonally adjusted"),
        Kpi(f"Trimmed mean CPI, {when(s.get('trimmed_mean_yoy'), True)}", latest(s.get("trimmed_mean_yoy"), ".1f"), "Year-ended"),
        Kpi(f"Business credit, {when(s.get('credit_business'))}", latest(s.get("credit_business"), ".1f"), "Year-ended growth"),
        Kpi(f"Home values, {hv['date'].iloc[-1]:%b %Y}" if len(hv) else "Home values",
            f"{hv['mom'].iloc[-1]:+.1f}%" if len(hv) else "n/a", "Month on month, Cotality"),
    ]


def cards(d) -> list[Card]:
    s, hv = d.series, d.home_values
    return [
        Card("Cash rate", "RBA cash rate target, %. Table F1.1.", charts.cash_rate(s.get("cash_rate")), "c-cash"),
        Card("Unemployment", "Seasonally adjusted, %. Table H5 (ABS Labour Force).",
             charts.unemployment(s.get("unemployment")), "c-unemp"),
        Card("Inflation vs target", "Year-ended, quarterly, %. Table G1 (ABS CPI).",
             charts.inflation(s.get("cpi_yoy"), s.get("trimmed_mean_yoy")), "c-cpi"),
        Card("Credit growth by sector", "Year-ended growth, %. Table D1.", charts.credit(s), "c-credit"),
        Card("Real GDP growth", "Year-ended, %. Table H1 (ABS National Accounts).", charts.gdp(s.get("gdp_yoy")), "c-gdp"),
        Card("Home values", "Cotality national HVI, monthly change %. Red bars are declines. Updated manually.",
             charts.home_values(hv), "c-home"),
        Card("Housing loan arrears", "Share of ADI housing credit outstanding, %. APRA quarterly property exposures, refreshed daily.",
             charts.housing_npl(s.get("apra_housing_npl"), s.get("apra_housing_pastdue")), "c-npl"),
        Card("Company insolvencies", "Companies entering external administration (ASIC Series 1): monthly and rolling 12-month total.",
             charts.insolvencies(s.get("asic_insolvencies"), s.get("asic_insolvencies_12m")), "c-insolv"),
        Card("Household debt to income", "Ratio of household debt to annualised disposable income, %. Table E2.",
             charts.debt_to_income(s.get("household_dti")), "c-dti"),
    ]


def status_rows(d) -> list[tuple[str, str, str, str]]:
    """(series, source table, latest observation, origin) for the status panel."""
    rows = []
    for key, spec in SPEC_BY_KEY.items():
        s = d.series.get(key)
        rows.append((spec.label, f"RBA {spec.table.upper()} ({spec.series_id})",
                     when(s) if s is not None else "n/a", d.origin.get(key, "missing")))
    for key, label, src in (("apra_housing_npl", "Housing loans non-performing", "APRA property exposures (xlsx)"),
                            ("asic_insolvencies", "Company insolvencies, monthly", "ASIC Series 1 (xlsx)")):
        s = d.series.get(key)
        rows.append((label, src, when(s) if s is not None else "n/a", d.origin.get(key, "missing")))
    return rows


STATUS_NOTE = ("'live' = fetched from the RBA when the page was built; 'daily' = refreshed each morning by the "
               "GitHub Action (APRA, ASIC); 'snapshot' = last saved copy. Manual series (data/manual): Cotality "
               "Home Value Index and the RBA Financial Stability Review cash-flow shortfall estimate.")
FOOTER = "Data: Reserve Bank of Australia, Australian Bureau of Statistics, Cotality, APRA, ASIC. Not investment advice."
