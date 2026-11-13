"""Credit risk scorecard: is each macro driver moving toward more or less risk?"""
from __future__ import annotations

import math

import pandas as pd

from .specs import SCORE_ITEMS

RISING, EASING, FLAT, NONE = "Risk rising", "Risk easing", "Unchanged", "No comparison"


def signal(latest: float | None, prior: float | None, higher_is_worse: bool, tol: float = 1e-9) -> str:
    if latest is None or prior is None or _isnan(latest) or _isnan(prior):
        return NONE
    diff = latest - prior
    if abs(diff) < tol:
        return FLAT
    worse = diff > 0 if higher_is_worse else diff < 0
    return RISING if worse else EASING


def _isnan(x) -> bool:
    try:
        return math.isnan(float(x))
    except (TypeError, ValueError):
        return True


def period_label(ts: pd.Timestamp, freq: str) -> str:
    if freq == "Q":
        return f"{ts.year} Q{(ts.month - 1) // 3 + 1}"
    return ts.strftime("%b %Y")


def infer_freq(s: pd.Series) -> str:
    if len(s) < 2:
        return "M"
    gap = s.index.to_series().diff().dt.days.median()
    return "Q" if gap and gap > 45 else "M"


def prior_point(s: pd.Series, months: int = 12) -> tuple[pd.Timestamp, float] | None:
    """Observation about `months` earlier (within 45 days), else the previous one."""
    if len(s) < 2:
        return None
    last = s.index[-1]
    target = last - pd.DateOffset(months=months)
    earlier = s[s.index <= last - pd.Timedelta(days=1)]
    gaps = pd.Series(abs(earlier.index - target), index=earlier.index)
    if len(gaps) and gaps.min() <= pd.Timedelta(days=45):
        idx = gaps.idxmin()
        return idx, float(earlier.loc[idx])
    return earlier.index[-1], float(earlier.iloc[-1])


def series_rows(series: dict[str, pd.Series], origin: dict[str, str]) -> list[dict]:
    rows = []
    for item in SCORE_ITEMS:
        s = series.get(item.key)
        if s is None or s.empty:
            continue
        freq = infer_freq(s)
        latest_d, latest_v = s.index[-1], float(s.iloc[-1])
        pp = prior_point(s)
        rows.append(
            {
                "Indicator": item.label,
                "Latest": round(latest_v, 2),
                "Period": period_label(latest_d, freq),
                "Prior": round(pp[1], 2) if pp else None,
                "Prior period": period_label(pp[0], freq) if pp else "",
                "Signal": signal(latest_v, pp[1] if pp else None, item.higher_is_worse),
                "Source": "RBA" + (" (snapshot)" if origin.get(item.key) == "snapshot" else ""),
                "Note": item.note,
            }
        )
    return rows


def manual_rows(stress: pd.DataFrame) -> list[dict]:
    rows = []
    for r in stress.itertuples(index=False):
        prior = None if pd.isna(r.prior) else float(r.prior)
        hiw = str(r.higher_is_worse).strip().lower() in ("true", "1", "yes")
        rows.append(
            {
                "Indicator": r.indicator,
                "Latest": float(r.latest),
                "Period": r.period,
                "Prior": prior,
                "Prior period": "" if pd.isna(r.prior_period) else r.prior_period,
                "Signal": signal(float(r.latest), prior, hiw),
                "Source": r.source,
                "Note": "" if pd.isna(r.note) else r.note,
            }
        )
    return rows


def build_scorecard(series, origin, stress) -> pd.DataFrame:
    return pd.DataFrame(series_rows(series, origin) + manual_rows(stress))


def summary(score: pd.DataFrame) -> tuple[int, int]:
    """(indicators signalling rising risk, indicators with a comparison point)."""
    comparable = score[score["Signal"] != NONE]
    return int((comparable["Signal"] == RISING).sum()), int(len(comparable))
