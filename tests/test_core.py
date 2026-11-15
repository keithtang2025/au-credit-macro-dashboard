import os

import pandas as pd
import pytest

os.environ["LIVE_DATA"] = "0"

from src.rba import SeriesSpec, parse_rba_csv, select_series  # noqa: E402
from src.scorecard import EASING, NONE, RISING, prior_point, signal, summary  # noqa: E402

SAMPLE = """F1.1 INTEREST RATES AND YIELDS – MONEY MARKET,,
Title,Cash Rate Target,Interbank Overnight Cash Rate
Description,Cash Rate Target,Interbank Overnight Cash Rate
Frequency,Monthly,Monthly
Type,Original,Original
Units,Per cent,Per cent
,,
,,
Source,RBA,RBA
Publication date,04-Nov-2026,04-Nov-2026
Series ID,FIRMMCRT,FIRMMCRI
31-Aug-2026,4.35,4.34
30-Sep-2026,4.60,
31-Oct-2026,4.60,4.59
"""


def test_parse_rba_csv():
    t = parse_rba_csv(SAMPLE)
    assert list(t.data.columns) == ["FIRMMCRT", "FIRMMCRI"]
    assert t.titles["FIRMMCRT"] == "Cash Rate Target"
    assert t.data.loc["2026-10-31", "FIRMMCRT"] == pytest.approx(4.60)
    assert pd.isna(t.data.loc["2026-09-30", "FIRMMCRI"])


def test_select_by_id_and_title_fallback():
    t = parse_rba_csv(SAMPLE)
    by_id = select_series(t, SeriesSpec("cash", "f1.1", "FIRMMCRT", "nomatch", "x"))
    assert by_id.iloc[-1] == pytest.approx(4.60)
    by_title = select_series(t, SeriesSpec("ib", "f1.1", "RENAMED", r"^interbank overnight", "x"))
    assert len(by_title) == 2  # NaN dropped
    with pytest.raises(KeyError):
        select_series(t, SeriesSpec("zz", "f1.1", "NOPE", r"^nothing$", "x"))


def test_signal_directions():
    assert signal(4.85, 3.60, higher_is_worse=True) == RISING
    assert signal(2.1, 2.5, higher_is_worse=False) == RISING
    assert signal(14152, 14722, higher_is_worse=True) == EASING
    assert signal(0.85, None, higher_is_worse=True) == NONE


def test_prior_point_prefers_12_months():
    idx = pd.date_range("2025-01-31", periods=14, freq="ME")
    s = pd.Series(range(14), index=idx, dtype=float)
    d, v = prior_point(s)
    assert d == pd.Timestamp("2025-02-28") and v == 1.0
    short = s.iloc[-3:]
    d2, _ = prior_point(short)
    assert d2 == short.index[-2]


def test_snapshot_layout_builds():
    from src.data import build
    from src.scorecard import build_scorecard

    d = build(use_live=False)
    assert "cash_rate" in d.series and d.origin["cash_rate"] == "snapshot"
    score = build_scorecard(d.series, d.origin, d.stress)
    up, total = summary(score)
    assert total >= up > 0

    import app

    layout = app.serve_layout()
    assert layout is not None


STALE = """Title,Credit; Total; 12-month ended growth,Credit; Total; 12-month ended growth
Series ID,OLDID,NEWID
30-Jun-2019,3.3,
31-Jul-2026,,8.4
31-Aug-2026,,8.4
30-Sep-2026,,8.4
"""


def test_select_prefers_current_series_over_discontinued_id():
    t = parse_rba_csv(STALE)
    s = select_series(t, SeriesSpec("total", "d1", "OLDID", r"credit; total; 12-month", "x"))
    assert s.index[-1] == pd.Timestamp("2026-09-30")


DAILY = """Title,Cash Rate Target
Series ID,FIRMMCRTD
30-Oct-2026,4.60
03-Nov-2026,4.60
04-Nov-2026,4.85
13-Nov-2026,4.85
"""


def test_daily_series_to_month_end_includes_current_month():
    t = parse_rba_csv(DAILY)
    s = select_series(t, SeriesSpec("cash_rate", "f1", "FIRMMCRTD", r"^cash rate", "x", to_month_end=True))
    assert s.iloc[-1] == pytest.approx(4.85)
    assert s.index[-1] == pd.Timestamp("2026-11-30")


def test_history_records_new_and_revised(tmp_path, monkeypatch):
    from src import history

    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path)
    monkeypatch.setattr(history, "VINTAGES", tmp_path / "vintages.csv")
    monkeypatch.setattr(history, "REFRESH_LOG", tmp_path / "refresh_log.csv")
    idx = pd.to_datetime(["2026-07-31", "2026-08-31"])
    c1 = history.record({"u": pd.Series([4.5, 4.6], index=idx)}, {}, pd.Timestamp("2026-09-15"))
    assert c1 == {"new": 2, "revised": 0}
    # same data again: nothing new; then a revision plus a new month
    assert history.record({"u": pd.Series([4.5, 4.6], index=idx)}, {}, pd.Timestamp("2026-09-16")) == {"new": 0, "revised": 0}
    idx2 = pd.to_datetime(["2026-07-31", "2026-08-31", "2026-09-30"])
    c3 = history.record({"u": pd.Series([4.5, 4.7, 4.7], index=idx2)}, {"x": "boom"}, pd.Timestamp("2026-10-16"))
    assert c3 == {"new": 1, "revised": 1}
    # point-in-time view before the revision still shows the first print
    assert history.as_of("u", "2026-09-30").loc["2026-08-31"] == pytest.approx(4.6)
    assert history.as_of("u", "2026-10-31").loc["2026-08-31"] == pytest.approx(4.7)
    rev = history.revisions("u")
    assert len(rev) == 1 and rev.iloc[0]["previous"] == pytest.approx(4.6)
    log = pd.read_csv(tmp_path / "refresh_log.csv")
    assert set(log["status"]) == {"ok", "failed"} and len(log) == 4
