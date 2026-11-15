# Australia Credit Risk Macro Dashboard

A Plotly Dash app tracking the macro drivers of Australian credit risk: the RBA cash rate, unemployment, inflation, credit growth, GDP, household leverage, housing collateral values and borrower stress indicators. A scorecard flags whether each driver is moving toward higher or lower credit risk.

**Live data:** RBA statistical tables (F1.1, D1, E2), plus the ABS labour force, CPI and national accounts series the RBA republishes (H5, G1, H1). The app fetches them on page load (cached for 6 hours). If the RBA site is unreachable, it falls back to the snapshot in `data/snapshot/`, and a GitHub Action refreshes that snapshot daily.

**Automated agency data:** each morning the GitHub Action also finds and downloads the latest APRA *Quarterly ADI property exposures* workbook (housing loans non-performing, % of credit outstanding) and ASIC *Insolvency statistics Series 1 and 2* workbook (companies entering external administration, monthly and rolling 12 months). Workbook URLs change every release, so the script reads the link from each publication page and locates series by their labels, not fixed cells. What it found is written to `data/debug/source_report.md` on every run.

**Manual data (no free feed):** Cotality home values and the RBA Financial Stability Review cash-flow shortfall estimate. Update `data/manual/` when new releases come out. Manual rows with a `replaced_by` value are hidden once that automated series is available.

## Project layout

```
app.py                      Dash app (layout, KPI cards, scorecard, charts)
src/rba.py                  RBA CSV downloader and parser
src/agencies.py             APRA and ASIC workbook discovery and parsing
src/xlsx_scan.py            Label-based series finder for Excel workbooks
src/specs.py                Series to fetch (table, series ID, title fallback) and scorecard rules
src/data.py                 Live fetch -> snapshot fallback, 6-hour cache
src/scorecard.py            Risk signal logic (latest vs ~12 months earlier)
src/charts.py               Plotly figures
data/snapshot/*.csv         Fallback copies of live series (auto-refreshed)
data/manual/*.csv           Hand-maintained series
data/debug/source_report.md What the last refresh found in the APRA/ASIC workbooks
data/history/*.csv          Append-only archive of values, revisions and refresh runs
src/history.py              Archive writer and point-in-time helpers (as_of, revisions)
scripts/refresh_snapshot.py Used by the scheduled GitHub Action
.github/workflows/          CI tests + daily data refresh
render.yaml                 Render blueprint
```


## Static edition (GitHub Pages)

A server-free copy of the dashboard is published to GitHub Pages after every daily refresh, so it never sleeps the way Render's free plan does. `scripts/build_static.py` fetches the RBA tables, renders the same KPIs, scorecard and charts (from `src/page.py`, shared with the Dash app) into a single `site/index.html`, and `.github/workflows/pages.yml` deploys it.

One-time setup: **Settings → Pages → Build and deployment → Source: GitHub Actions**. The page then lives at `https://<your-user>.github.io/<repo-name>/`. To build it locally: `python scripts/build_static.py` and open `site/index.html`.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py              # http://localhost:8050
LIVE_DATA=0 python app.py  # snapshot only, no network
pytest -q                  # tests
```

## Deploy on Render

1. Push this repo to GitHub.
2. In Render: **New > Blueprint**, pick the repo. Render reads `render.yaml` and creates the web service (`gunicorn app:server`).
3. Each push to `main` redeploys, including the daily snapshot commits from GitHub Actions.

The free plan sleeps after inactivity, so the first visit after a while takes about 30 to 60 seconds to wake up.

## Scorecard method

For each series, the latest observation is compared with the one about 12 months earlier (within 45 days), or the previous observation if history is shorter. The signal is **Risk rising** when the move worsens borrower credit quality: a higher cash rate, unemployment, inflation, leverage, stress or insolvencies, or lower GDP growth or home values. Faster business credit growth is treated as rising risk (faster leverage build-up).

## Daily updates and data history

A GitHub Action (`.github/workflows/refresh-data.yml`) runs every day at 9:17am Sydney time (22:17 UTC). It fetches the RBA/ABS series and the APRA and ASIC workbooks, updates `data/snapshot/`, archives the data in `data/history/` and commits. Render redeploys on each commit. You can also run it any time from **Actions > Refresh data snapshot > Run workflow**.

The archive is append-only:

- `data/history/vintages.csv`: one row the first time each value is seen (`new`) and again whenever the RBA/ABS revises it (`revised`), stamped with the retrieval date.
- `data/history/refresh_log.csv`: one row per series per run (`ok`/`failed`, latest period and value), an audit trail of the feed.

Point-in-time views for analysis:

```python
from src.history import as_of, revisions
as_of("unemployment", "2026-12-31")   # series as it looked on that date
revisions("gdp_yoy")                  # every revision: old value, new value, date seen
```

Note: GitHub pauses scheduled workflows in a repo with no activity for 60 days. The daily data commits normally count as activity, but if the workflow ever shows as disabled, re-enable it on the Actions tab.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LIVE_DATA` | `1` | `0` = use snapshot only |
| `CACHE_TTL_SECONDS` | `21600` | How long fetched data is reused |
| `PORT` | `8050` | Local port |

## Maintaining series

If the RBA renames a series ID, the fetcher falls back to matching the series title (`title_pattern` in `src/specs.py`). The **Data sources and status** panel at the bottom of the page shows whether each series is live or from the snapshot.

Data: Reserve Bank of Australia and Australian Bureau of Statistics (CC BY 4.0), Cotality, ASIC, S&P Global Ratings. Not investment advice.
