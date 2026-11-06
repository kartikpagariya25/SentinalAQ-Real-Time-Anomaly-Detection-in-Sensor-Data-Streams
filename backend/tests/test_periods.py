import pandas as pd
import pytest

from app.ingest import PERIODS, period_window


@pytest.mark.parametrize("period,anchor,start,end", [
    ("daily", "2026-03-04 15:30", "2026-03-04", "2026-03-05"),
    ("weekly", "2026-03-04", "2026-03-02", "2026-03-09"),      # Monday-based
    ("weekly", "2026-03-08", "2026-03-02", "2026-03-09"),      # Sunday stays in the same week
    ("monthly", "2026-02-17", "2026-02-01", "2026-03-01"),
    ("monthly", "2026-12-31", "2026-12-01", "2027-01-01"),
    ("yearly", "2026-07-01", "2026-01-01", "2027-01-01"),
])
def test_period_window(period, anchor, start, end):
    assert period_window(period, anchor) == (pd.Timestamp(start), pd.Timestamp(end))


def test_every_period_has_a_window():
    for p in PERIODS:
        s, e = period_window(p, "2026-05-05")
        assert e > s


def test_unknown_period_raises():
    with pytest.raises(ValueError):
        period_window("hourly", "2026-05-05")
