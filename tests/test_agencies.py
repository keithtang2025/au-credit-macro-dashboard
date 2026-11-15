import io
from datetime import datetime

import pandas as pd
import pytest
from openpyxl import Workbook

from src.agencies import apra_npl_from_sheets, asic_from_sheets, find_link, rolling_12m
from src.xlsx_scan import find_series, load_sheets, to_period


def _book(sheets: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


QTRS = [datetime(2025, 6, 30), datetime(2025, 9, 30), datetime(2025, 12, 31), datetime(2026, 3, 31), datetime(2026, 6, 30)]


def test_to_period_variants():
    for v in ("Jun 2026", "Jun-26", "June 2026", "Jun Qtr 2026", "2026-06", datetime(2026, 6, 30)):
        assert to_period(v) == pd.Timestamp("2026-06-30"), v
    assert to_period("Total") is None


def test_find_link_decodes_and_excludes():
    html = ('<a href="/system/files/2020-03/Quarterly%20property%20exposures%20-%20Historical%20data.xlsx">old</a>'
            '<a href="/system/files/2026-09/Quarterly%20authorised%20deposit-taking%20institution%20property'
            '%20exposures%20statistics%20June%202026.xlsx">new</a>')
    url = find_link(html, "https://www.apra.gov.au/page", r"property exposures statistics", exclude=r"historical")
    assert url.startswith("https://www.apra.gov.au/system/files/2026-09/") and "June%202026" in url


def test_apra_ratio_row_dates_across():
    content = _book({
        "Contents": [["Table 1 Residential"]],
        "Table 2": [
            ["Residential property exposures - risk indicators"],
            ["$ million / per cent", *QTRS],
            ["Non-performing loans - owner-occupied (%)", 0.7, 0.75, 0.8, 0.85, 0.9],
            ["Non-performing loans - total (%)", 0.8, 0.85, 0.9, 0.95, 1.02],
        ],
        "Commercial": [["x", *QTRS], ["Non-performing share (%)", 1, 1, 1, 1, 1]],
    })
    s, how = apra_npl_from_sheets(load_sheets(content))
    assert s.iloc[-1] == pytest.approx(1.02) and "total" in how


def test_apra_levels_dates_down_computes_share():
    rows = [["Housing credit"], ["Quarter", "Total credit outstanding ($m)", "Non-performing ($m)"]]
    rows += [[d, 2_400_000.0, 2_400_000.0 * p / 100] for d, p in zip(QTRS, [0.8, 0.85, 0.9, 0.95, 1.0])]
    s, how = apra_npl_from_sheets(load_sheets(_book({"Table 1a": rows})))
    assert s.iloc[-1] == pytest.approx(1.0) and "/" in how


def test_apra_no_match_raises():
    with pytest.raises(LookupError):
        apra_npl_from_sheets(load_sheets(_book({"T": [["x", *QTRS], ["Credit growth", 1, 2, 3, 4, 5]]})))


def test_asic_prefers_series1_monthly_total():
    months = pd.date_range("2024-07-31", periods=24, freq="ME")
    s1 = [["Table 1.2 Companies entering external administration, MONTHLY"], ["Month", "NSW", "VIC", "Total"]]
    s1 += [[d.to_pydatetime(), 400, 300, 900 + i] for i, d in enumerate(months)]
    s2 = [["Table 2.2 Appointments, MONTHLY"], ["Month", "Total"]]
    s2 += [[d.to_pydatetime(), 1500] for d in months]
    sheets = load_sheets(_book({"2.2": s2, "1.2": s1}))
    s, how = asic_from_sheets(sheets)
    assert "'1.2'" in how and s.iloc[-1] == 923
    r12 = rolling_12m(s)
    assert r12.iloc[-1] == sum(900 + i for i in range(12, 24))


def test_manual_rows_replaced_when_automated():
    from src.scorecard import manual_rows

    stress = pd.read_csv("data/manual/stress_indicators.csv")
    all_rows = manual_rows(stress, set())
    auto_rows = manual_rows(stress, {"asic_insolvencies_12m", "apra_housing_npl"})
    assert len(all_rows) == 5 and len(auto_rows) == 2


def test_find_series_requires_min_points():
    sheets = {"s": [["x", *QTRS[:2], "Jun 2026", "Sep 2026"], ["Total", 1, None, None, None]]}
    assert find_series(sheets, r"^total$") == []
