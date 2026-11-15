"""Plotly figures for the dashboard."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

BLUE, ORANGE, TEAL, GREY, RED = "#2563eb", "#ea580c", "#0d9488", "#94a3b8", "#dc2626"
RBA_TARGET = (2.0, 3.0)


def _base(fig: go.Figure, ysuffix: str = "%", height: int = 300) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="x unified",
        font=dict(family="Inter, system-ui, sans-serif", size=12),
    )
    fig.update_yaxes(ticksuffix=ysuffix, gridcolor="#eef2f7", zeroline=False)
    fig.update_xaxes(showgrid=False)
    return fig


def empty(msg: str = "No data available") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False, font=dict(color=GREY))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _base(fig)


def _last_label(fig, s: pd.Series, color: str, fmt: str = "{:.2f}%"):
    fig.add_annotation(
        x=s.index[-1], y=s.iloc[-1], text=fmt.format(s.iloc[-1]), showarrow=False,
        yshift=14, xanchor="right", font=dict(color=color),
    )


def cash_rate(s: pd.Series | None) -> go.Figure:
    if s is None or s.empty:
        return empty()
    s = s[s.index >= s.index[-1] - pd.DateOffset(years=5)]
    fig = go.Figure(go.Scatter(x=s.index, y=s.values, mode="lines", line=dict(color=BLUE, width=2.5, shape="hv"),
                               name="Cash rate target", hovertemplate="%{y:.2f}%<extra></extra>"))
    _last_label(fig, s, BLUE)
    return _base(fig)


def unemployment(s: pd.Series | None) -> go.Figure:
    if s is None or s.empty:
        return empty()
    s = s[s.index >= s.index[-1] - pd.DateOffset(years=5)]
    fig = go.Figure(go.Scatter(x=s.index, y=s.values, mode="lines+markers", line=dict(color=BLUE, width=2),
                               marker=dict(size=4), name="Unemployment rate", hovertemplate="%{y:.1f}%<extra></extra>"))
    _last_label(fig, s, BLUE, "{:.1f}%")
    return _base(fig)


def inflation(cpi: pd.Series | None, tm: pd.Series | None) -> go.Figure:
    if (cpi is None or cpi.empty) and (tm is None or tm.empty):
        return empty()
    fig = go.Figure()
    fig.add_hrect(y0=RBA_TARGET[0], y1=RBA_TARGET[1], fillcolor="#16a34a", opacity=0.08, line_width=0,
                  annotation_text="RBA target 2 to 3%", annotation_position="bottom left",
                  annotation_font=dict(color="#15803d", size=11))
    for s, name, color in ((cpi, "Headline CPI", BLUE), (tm, "Trimmed mean", ORANGE)):
        if s is not None and not s.empty:
            s = s[s.index >= s.index[-1] - pd.DateOffset(years=5)]
            fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines+markers", name=name,
                                     line=dict(color=color, width=2), marker=dict(size=5),
                                     hovertemplate="%{y:.1f}%"))
    return _base(fig)


def credit(series: dict[str, pd.Series]) -> go.Figure:
    parts = [("credit_housing", "Housing", BLUE), ("credit_business", "Business", ORANGE),
             ("credit_personal", "Personal", TEAL)]
    fig = go.Figure()
    for key, name, color in parts:
        s = series.get(key)
        if s is None or s.empty:
            continue
        s = s[s.index >= s.index[-1] - pd.DateOffset(years=5)]
        fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines+markers", name=name,
                                 line=dict(color=color, width=2), marker=dict(size=4), hovertemplate="%{y:.1f}%"))
    return _base(fig) if fig.data else empty()


def gdp(s: pd.Series | None) -> go.Figure:
    if s is None or s.empty:
        return empty()
    s = s.iloc[-12:]
    labels = [f"Q{(d.month - 1) // 3 + 1} {d.year}" for d in s.index]
    fig = go.Figure(go.Bar(x=labels, y=s.values, marker_color=BLUE, text=[f"{v:.1f}%" for v in s.values],
                           textposition="outside", hovertemplate="%{x}: %{y:.1f}%<extra></extra>"))
    fig = _base(fig)
    fig.update_layout(hovermode="closest")
    return fig


def home_values(df: pd.DataFrame | None) -> go.Figure:
    if df is None or df.empty:
        return empty()
    colors = [RED if v < 0 else BLUE for v in df["mom"]]
    labels = df["date"].dt.strftime("%b %y")
    fig = go.Figure(go.Bar(x=labels, y=df["mom"], marker_color=colors,
                           text=[f"{v:+.1f}%" for v in df["mom"]], textposition="outside",
                           hovertemplate="%{x}: %{y:+.1f}%<extra></extra>"))
    fig = _base(fig)
    fig.update_layout(hovermode="closest")
    fig.add_hline(y=0, line_color=GREY, line_width=1)
    return fig


def debt_to_income(s: pd.Series | None) -> go.Figure:
    if s is None or s.empty:
        return empty("Loads live from RBA table E2")
    s = s[s.index >= s.index[-1] - pd.DateOffset(years=10)]
    fig = go.Figure(go.Scatter(x=s.index, y=s.values, mode="lines", line=dict(color=BLUE, width=2),
                               name="Debt to income", hovertemplate="%{y:.1f}%<extra></extra>"))
    _last_label(fig, s, BLUE, "{:.0f}%")
    return _base(fig)


def housing_npl(s: pd.Series | None, pastdue: pd.Series | None = None) -> go.Figure:
    if s is None or s.empty:
        return empty("Loads from APRA after the next daily refresh")
    fig = go.Figure()
    for series, name, color in ((s, "Non-performing (90+ days or impaired)", RED), (pastdue, "30-89 days past due", ORANGE)):
        if series is None or series.empty:
            continue
        series = series[series.index >= series.index[-1] - pd.DateOffset(years=8)]
        fig.add_trace(go.Scatter(x=series.index, y=series.values, mode="lines+markers", line=dict(color=color, width=2),
                                 marker=dict(size=4), name=name, hovertemplate="%{y:.2f}%"))
        _last_label(fig, series, color)
    return _base(fig)


def _nice_step(raw: float) -> float:
    """Smallest 'round' step (1, 2, 2.5, 5 x 10^k) at least raw."""
    import math

    if raw <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(raw))
    for f in (1, 2, 2.5, 5, 10):
        if f * mag >= raw:
            return f * mag
    return 10 * mag


def insolvencies(monthly: pd.Series | None, r12: pd.Series | None) -> go.Figure:
    if monthly is None or monthly.empty:
        return empty("Loads from ASIC after the next daily refresh")
    m = monthly[monthly.index >= monthly.index[-1] - pd.DateOffset(years=5)]
    fig = go.Figure(go.Bar(x=m.index, y=m.values, name="Monthly", marker_color=GREY,
                           hovertemplate="%{x|%b %Y}: %{y:,.0f}<extra></extra>"))
    if r12 is not None and not r12.empty:
        r = r12[r12.index >= m.index[0]]
        fig.add_trace(go.Scatter(x=r.index, y=r.values, name="Rolling 12 months (right)", yaxis="y2",
                                 line=dict(color=ORANGE, width=2.5), hovertemplate="%{y:,.0f}<extra></extra>"))
        # both axes: 4 equal intervals with round steps, so gridlines line up
        ls, rs = _nice_step(m.max() / 4), _nice_step(r.max() / 4)
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, tickformat=",.0f",
                                      range=[0, rs * 4.05], tick0=0, dtick=rs))
        fig.update_layout(yaxis=dict(range=[0, ls * 4.05], tick0=0, dtick=ls))
    fig = _base(fig, ysuffix="")
    fig.update_yaxes(tickformat=",.0f")
    return fig
