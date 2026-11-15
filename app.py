"""Australia Credit Risk Macro Dashboard (Plotly Dash).

Run locally:   python app.py
Production:    gunicorn app:server
"""
from __future__ import annotations

import os

import pandas as pd
from dash import Dash, dash_table, dcc, html

from src import charts
from src.data import get_data
from src.scorecard import EASING, RISING, build_scorecard, summary
from src.specs import SPEC_BY_KEY

app = Dash(__name__, title="Australia Credit Risk Macro Dashboard")
server = app.server

CONFIG = {"displayModeBar": False, "responsive": True}


def _latest(s: pd.Series | None, fmt: str, signed: bool = False) -> str:
    if s is None or s.empty:
        return "n/a"
    v = float(s.iloc[-1])
    return (f"{v:+{fmt}}" if signed else f"{v:{fmt}}") + "%"


def _when(s: pd.Series | None, quarterly: bool = False) -> str:
    if s is None or s.empty:
        return ""
    d = s.index[-1]
    return f"Q{(d.month - 1) // 3 + 1} {d.year}" if quarterly else d.strftime("%b %Y")


def kpi(label: str, value: str, sub: str) -> html.Div:
    return html.Div(className="card kpi", children=[
        html.Div(label, className="muted small"), html.Div(value, className="big"), html.Div(sub, className="muted small"),
    ])


def chart_card(title: str, note: str, fig, cid: str) -> html.Div:
    return html.Div(className="card", id=cid, children=[
        html.H3(title), html.P(note, className="muted small"),
        dcc.Graph(figure=fig, config=CONFIG, style={"height": "300px"}),
    ])


def scorecard_table(df: pd.DataFrame) -> dash_table.DataTable:
    cols = ["Indicator", "Latest", "Period", "Prior", "Prior period", "Signal", "Source"]
    return dash_table.DataTable(
        data=df[cols].to_dict("records"),
        columns=[{"name": c, "id": c, "type": "numeric" if c in ("Latest", "Prior") else "text",
                  "format": {"specifier": ",.2~f"} if c in ("Latest", "Prior") else None} for c in cols],
        tooltip_data=[{"Indicator": n} if n else {} for n in df["Note"].fillna("")],
        style_as_list_view=True,
        style_table={"overflowX": "auto"},
        style_header={"fontWeight": 600, "backgroundColor": "#f8fafc", "color": "#475569", "fontSize": 12},
        style_cell={"fontFamily": "Inter, system-ui, sans-serif", "fontSize": 13, "padding": "8px 10px",
                    "textAlign": "left", "border": "none", "borderBottom": "1px solid #e5e7eb"},
        style_cell_conditional=[{"if": {"column_id": c}, "textAlign": "right"} for c in ("Latest", "Prior")],
        style_data_conditional=[
            {"if": {"filter_query": f'{{Signal}} = "{RISING}"', "column_id": "Signal"}, "color": "#dc2626", "fontWeight": 600},
            {"if": {"filter_query": f'{{Signal}} = "{EASING}"', "column_id": "Signal"}, "color": "#16a34a", "fontWeight": 600},
        ],
    )


def status_table(d) -> html.Table:
    rows = []
    for key, spec in SPEC_BY_KEY.items():
        s = d.series.get(key)
        origin = d.origin.get(key, "missing")
        rows.append(html.Tr([
            html.Td(spec.label), html.Td(f"RBA {spec.table.upper()} ({spec.series_id})"),
            html.Td(_when(s) if s is not None else "n/a"),
            html.Td(origin, className=f"badge {origin}"),
        ]))
    for key, label, src in (("apra_housing_npl", "Housing loans non-performing", "APRA property exposures (xlsx)"),
                            ("asic_insolvencies", "Company insolvencies, monthly", "ASIC Series 1 (xlsx)")):
        s = d.series.get(key)
        origin = d.origin.get(key, "missing")
        rows.append(html.Tr([html.Td(label), html.Td(src), html.Td(_when(s) if s is not None else "n/a"),
                             html.Td(origin, className=f"badge {origin}")]))
    return html.Table(className="status", children=[
        html.Thead(html.Tr([html.Th("Series"), html.Th("Table (ID)"), html.Th("Latest obs."), html.Th("Data")])),
        html.Tbody(rows),
    ])


def serve_layout():
    d = get_data()
    s = d.series
    score = build_scorecard(s, d.origin, d.stress)
    n_up, n_cmp = summary(score)
    n_live = sum(1 for o in d.origin.values() if o == "live")
    hv = d.home_values

    return html.Div(className="page", children=[
        html.Header(children=[
            html.H1("Australia: macro drivers of credit risk"),
            html.P(
                f"Loaded {d.loaded_at:%d %b %Y %H:%M} Sydney time. {n_live} of {len(SPEC_BY_KEY)} RBA/ABS series "
                f"live, the rest from the bundled snapshot. Housing and stress indicators are updated manually.",
                className="muted small",
            ),
            html.P(className="takeaway", children=[
                "Of the indicators with a comparison point, ", html.B(str(n_up)), " of ", html.B(str(n_cmp)),
                " are moving toward higher credit risk.",
            ]),
        ]),
        html.Div(className="kpis", children=[
            kpi(f"RBA cash rate, {_when(s.get('cash_rate'))}", _latest(s.get("cash_rate"), ".2f"), "Target rate"),
            kpi(f"Unemployment, {_when(s.get('unemployment'))}", _latest(s.get("unemployment"), ".1f"), "Seasonally adjusted"),
            kpi(f"Trimmed mean CPI, {_when(s.get('trimmed_mean_yoy'), True)}", _latest(s.get("trimmed_mean_yoy"), ".1f"), "Year-ended"),
            kpi(f"Business credit, {_when(s.get('credit_business'))}", _latest(s.get("credit_business"), ".1f"), "Year-ended growth"),
            kpi(f"Home values, {hv['date'].iloc[-1]:%b %Y}" if len(hv) else "Home values",
                f"{hv['mom'].iloc[-1]:+.1f}%" if len(hv) else "n/a", "Month on month, Cotality"),
        ]),
        html.Section(className="card", id="scorecard", children=[
            html.H2("Credit risk scorecard"),
            html.P("Signal compares the latest print with the one about 12 months earlier (or the previous print "
                   "where history is short), in the direction that worsens borrower credit quality. Hover an "
                   "indicator for notes.", className="muted small"),
            scorecard_table(score),
        ]),
        html.Div(className="grid", children=[
            chart_card("Cash rate", "RBA cash rate target, %. Table F1.1.", charts.cash_rate(s.get("cash_rate")), "c-cash"),
            chart_card("Unemployment", "Seasonally adjusted, %. Table H5 (ABS Labour Force).",
                       charts.unemployment(s.get("unemployment")), "c-unemp"),
            chart_card("Inflation vs target", "Year-ended, quarterly, %. Table G1 (ABS CPI).",
                       charts.inflation(s.get("cpi_yoy"), s.get("trimmed_mean_yoy")), "c-cpi"),
            chart_card("Credit growth by sector", "Year-ended growth, %. Table D1.", charts.credit(s), "c-credit"),
            chart_card("Real GDP growth", "Year-ended, %. Table H1 (ABS National Accounts).", charts.gdp(s.get("gdp_yoy")), "c-gdp"),
            chart_card("Home values", "Cotality national HVI, monthly change %. Red bars are declines. Updated manually.",
                       charts.home_values(hv), "c-home"),
            chart_card("Housing loans non-performing", "Share of ADI housing credit outstanding, %. APRA quarterly property exposures, refreshed daily.",
                       charts.housing_npl(s.get("apra_housing_npl")), "c-npl"),
            chart_card("Company insolvencies", "Companies entering external administration (ASIC Series 1): monthly and rolling 12-month total.",
                       charts.insolvencies(s.get("asic_insolvencies"), s.get("asic_insolvencies_12m")), "c-insolv"),
            chart_card("Household debt to income", "Ratio of household debt to annualised disposable income, %. Table E2.",
                       charts.debt_to_income(s.get("household_dti")), "c-dti"),
        ]),
        html.Details(className="card", children=[
            html.Summary("Data sources and status"),
            status_table(d),
            html.P("'live' = fetched from the RBA when the page loads; 'daily' = refreshed each morning by the "
                   "GitHub Action (APRA, ASIC); 'snapshot' = last saved copy. Manual series (data/manual): Cotality "
                   "Home Value Index and the RBA Financial Stability Review cash-flow shortfall estimate.",
                   className="muted small"),
        ]),
        html.Footer("Built with Plotly Dash. Data: Reserve Bank of Australia, Australian Bureau of Statistics, "
                    "Cotality, ASIC, S&P Global Ratings. Not investment advice.", className="muted small"),
    ])


app.layout = serve_layout

if __name__ == "__main__":
    app.run(debug=os.getenv("DEBUG", "0") == "1", host="0.0.0.0", port=int(os.getenv("PORT", "8050")))
