"""Which series the dashboard pulls, and how each one feeds the risk scorecard."""
from __future__ import annotations

from dataclasses import dataclass

from .rba import SeriesSpec

# Live series from RBA statistical tables. The RBA republishes the ABS labour
# force, CPI and national accounts series in tables H5, G1 and H1, so one
# parser covers RBA and ABS data. Series IDs are tried first; the title
# pattern is the fallback if an ID changes.
LIVE_SERIES: list[SeriesSpec] = [
    # Daily table first so a decision shows in the current month; the
    # monthly table (month-end values only) is the fallback.
    SeriesSpec("cash_rate", "f1", "FIRMMCRTD", r"^cash rate target", "RBA cash rate target", to_month_end=True),
    SeriesSpec("cash_rate", "f1.1", "FIRMMCRT", r"^cash rate target", "RBA cash rate target"),
    SeriesSpec("unemployment", "h5", "GLFSURSA", r"^unemployment rate", "Unemployment rate (SA)"),
    SeriesSpec("cpi_yoy", "g1", "GCPIAGYP", r"^year-ended inflation$", "Headline CPI, year-ended"),
    SeriesSpec(
        "trimmed_mean_yoy",
        "g1",
        "GCPIOCPMTMYP",
        r"year-ended.*trimmed mean|trimmed mean.*year-ended",
        "Trimmed mean CPI, year-ended",
    ),
    SeriesSpec("gdp_yoy", "h1", "GGDPCVGDPY", r"year-ended.*gdp|gdp.*year-ended", "Real GDP, year-ended growth"),
    SeriesSpec("credit_housing", "d1", "DGFACH12", r"credit; housing; 12-month", "Housing credit growth"),
    SeriesSpec(
        "credit_business",
        "d1",
        "DGFACBNF12",
        r"credit; non-financial business; 12-month",
        "Business credit growth",
    ),
    SeriesSpec("credit_personal", "d1", "DGFACOPF12", r"credit; other personal; 12-month", "Personal credit growth"),
    SeriesSpec("credit_total", "d1", "DGFACP12", r"credit; total; 12-month", "Total credit growth"),
    SeriesSpec(
        "household_dti",
        "e2",
        "BHFDDIT",
        r"household debt to (annualised )?(household )?(disposable )?income",
        "Household debt to income",
        unit="%",
    ),
]

SPEC_BY_KEY: dict[str, SeriesSpec] = {}
for _s in LIVE_SERIES:  # first spec per key is the primary source
    SPEC_BY_KEY.setdefault(_s.key, _s)


@dataclass(frozen=True)
class ScoreItem:
    key: str
    label: str
    higher_is_worse: bool
    note: str = ""


# Series-based scorecard rows: latest print vs the print about 12 months
# earlier (or the previous print when the history is too short).
SCORE_ITEMS: list[ScoreItem] = [
    ScoreItem("cash_rate", "RBA cash rate", True),
    ScoreItem("unemployment", "Unemployment rate", True),
    ScoreItem("cpi_yoy", "Headline CPI (y/y)", True),
    ScoreItem("trimmed_mean_yoy", "Trimmed mean CPI (y/y)", True),
    ScoreItem("gdp_yoy", "Real GDP growth (y/y)", False),
    ScoreItem("credit_business", "Business credit growth (y/y)", True, "Faster growth = faster leverage build-up"),
    ScoreItem("household_dti", "Household debt to income", True),
]
