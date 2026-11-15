"""Australia Credit Risk Macro Dashboard (Plotly Dash).

Run locally:   python app.py
Production:    gunicorn app:server
"""
from __future__ import annotations

import os

import pandas as pd
from dash import Dash, dash_table, dcc, html

from src import page
from src.data import get_data
from src.scorecard import EASING, RISING, build_scorecard, summary
from src.specs import SPEC_BY_KEY

app = Dash(__name__, title="Australia Credit Risk Macro Dashboard")
server = app.server

CONFIG = {"displayModeBar": False, "responsive": True}


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
    rows = [html.Tr([html.Td(a), html.Td(b), html.Td(c), html.Td(o, className=f"badge {o}")])
            for a, b, c, o in page.status_rows(d)]
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
        html.Div(className="kpis", children=[kpi(k.label, k.value, k.sub) for k in page.kpis(d)]),
        html.Section(className="card", id="scorecard", children=[
            html.H2("Credit risk scorecard"),
            html.P("Signal compares the latest print with the one about 12 months earlier (or the previous print "
                   "where history is short), in the direction that worsens borrower credit quality. Hover an "
                   "indicator for notes.", className="muted small"),
            scorecard_table(score),
        ]),
        html.Div(className="grid", children=[chart_card(c.title, c.note, c.fig, c.cid) for c in page.cards(d)]),
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
