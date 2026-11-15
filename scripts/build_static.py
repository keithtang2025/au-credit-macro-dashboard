"""Build a static copy of the dashboard for GitHub Pages.

    python scripts/build_static.py            # writes site/index.html

Uses the same snapshot, scorecard and charts as the Dash app (src/page.py), so the
two never drift apart. The page needs no server: charts are Plotly figures embedded
as JSON and drawn by plotly.js from a CDN.
"""
from __future__ import annotations

import html
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.io as pio  # noqa: E402

from src import page  # noqa: E402
from src.data import build  # noqa: E402
from src.scorecard import EASING, RISING, build_scorecard, summary  # noqa: E402
from src.specs import SPEC_BY_KEY  # noqa: E402

OUT = ROOT / "site"
CONFIG = {"displayModeBar": False, "responsive": True}
PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def when(s: pd.Series | None) -> str:
    if s is None or s.empty:
        return ""
    d = s.index[-1]
    if len(s) > 2 and s.index.to_series().diff().dt.days.median() > 45:
        return f"Q{(d.month - 1) // 3 + 1} {d.year}"
    return d.strftime("%b %Y")


def num(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def kpi_html(k: page.Kpi) -> str:
    return (f'<div class="card kpi"><div class="muted small">{esc(k.label)}</div>'
            f'<div class="big">{esc(k.value)}</div><div class="muted small">{esc(k.sub)}</div></div>')


def figure_html(fig, div_id: str) -> str:
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, config=CONFIG, div_id=div_id,
                       default_height="300px")


def scorecard_html(score: pd.DataFrame) -> str:
    if score.empty:
        return '<p class="muted">The scorecard fills in after the first daily refresh.</p>'
    cols = ["Indicator", "Latest", "Period", "Prior", "Prior period", "Signal", "Source"]
    head = "".join(f'<th class="{"num" if c in ("Latest", "Prior") else ""}">{c}</th>' for c in cols)
    rows = []
    for r in score.to_dict("records"):
        sig = r["Signal"]
        cls = "up" if sig == RISING else "down" if sig == EASING else ""
        note = r.get("Note") or ""
        rows.append(
            "<tr>"
            f'<td title="{esc(note)}">{esc(r["Indicator"])}{" ⓘ" if note else ""}</td>'
            f'<td class="num">{num(r["Latest"])}</td><td>{esc(r["Period"])}</td>'
            f'<td class="num">{num(r["Prior"])}</td><td>{esc(r["Prior period"])}</td>'
            f'<td class="sig {cls}">{esc(sig)}</td><td>{esc(r["Source"])}</td>'
            "</tr>")
    return f'<div class="scroll"><table class="score"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def status_html(d) -> str:
    rows = "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td><td>{esc(c)}</td><td class=\"badge {esc(o)}\">{esc(o)}</td></tr>"
                   for a, b, c, o in page.status_rows(d))
    return ('<table class="status"><thead><tr><th>Series</th><th>Table (ID)</th><th>Latest obs.</th><th>Data</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>')


EXTRA_CSS = """
.score { width: 100%; border-collapse: collapse; font-size: 13px; }
.score th { background: #f8fafc; color: #475569; font-size: 12px; font-weight: 600; }
.score th, .score td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #e5e7eb; white-space: nowrap; }
.score .num { text-align: right; font-variant-numeric: tabular-nums; }
.sig.up { color: #dc2626; font-weight: 600; }
.sig.down { color: #16a34a; font-weight: 600; }
.scroll { overflow-x: auto; }
.chart { height: 300px; width: 100%; overflow: hidden; }
.chart > div { width: 100% !important; }
.ribbon { font-size: 12px; background: #eef2ff; color: #3730a3; border-radius: 6px; padding: 6px 10px; display: inline-block; margin-bottom: 12px; }
"""


def build_html() -> str:
    d = build(use_live=True)  # the RBA tables are fetched at build time; the snapshot covers any failure
    s = d.series
    score = build_scorecard(s, d.origin, d.stress)
    n_up, n_cmp = summary(score) if not score.empty else (0, 0)
    n_live = sum(1 for o in d.origin.values() if o == "live")
    built = pd.Timestamp.now(tz="Australia/Sydney").strftime("%d %b %Y %H:%M Sydney time")

    cards = "".join(
        f'<div class="card" id="{esc(c.cid)}"><h3>{esc(c.title)}</h3><p class="muted small">{esc(c.note)}</p>'
        f'<div class="chart">{figure_html(c.fig, "fig-" + c.cid)}</div></div>'
        for c in page.cards(d))

    css = (ROOT / "assets" / "style.css").read_text() + EXTRA_CSS
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Australia Credit Risk Macro Dashboard</title>
<meta name="description" content="Macro drivers of credit risk in Australia, refreshed daily from official sources.">
<script src="{PLOTLY_CDN}" charset="utf-8"></script>
<style>{css}</style>
</head>
<body>
<div class="page">
<header>
<span class="ribbon">Static edition, rebuilt automatically after each daily data refresh (built {esc(built)})</span>
<h1>Australia: macro drivers of credit risk</h1>
<p class="muted small">{n_live} of {len(SPEC_BY_KEY)} RBA/ABS series fetched live when this page was built, the rest from
the saved snapshot. APRA and ASIC refresh daily; housing and stress indicators are updated manually.</p>
<p class="takeaway">Of the indicators with a comparison point, <b>{n_up}</b> of <b>{n_cmp}</b> are moving toward higher credit risk.</p>
</header>
<div class="kpis">{"".join(kpi_html(k) for k in page.kpis(d))}</div>
<section class="card" id="scorecard">
<h2>Credit risk scorecard</h2>
<p class="muted small">Signal compares the latest print with the one about 12 months earlier (or the previous print where
history is short), in the direction that worsens borrower credit quality. Hover an indicator marked ⓘ for notes.</p>
{scorecard_html(score)}
</section>
<div class="grid">{cards}</div>
<details class="card"><summary>Data sources and status</summary>
{status_html(d)}
<p class="muted small">{esc(page.STATUS_NOTE)}</p>
</details>
<footer class="muted small">Built with Plotly. {esc(page.FOOTER)}</footer>
</div>
<script>
// Charts are drawn while the page is still laying out; size them to their cards once it is done.
function fitCharts() {{ document.querySelectorAll('.js-plotly-plot').forEach(p => Plotly.Plots.resize(p)); }}
window.addEventListener('load', fitCharts);
document.querySelector('details') && document.querySelector('details').addEventListener('toggle', fitCharts);
</script>
</body>
</html>
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(build_html(), encoding="utf-8")
    (OUT / ".nojekyll").write_text("")
    print(f"wrote {OUT / 'index.html'}")


if __name__ == "__main__":
    main()
