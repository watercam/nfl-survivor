from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.survivor.calibration import movement_adjustment
from src.survivor.probability import (
    american_to_implied,
    no_vig_pair,
    pick_snapshot_at_or_before,
    reference_snapshot,
)
from src.survivor.types import Snapshot


def test_no_vig_pair_sums_to_one():
    a, b = no_vig_pair(-150, 130)
    assert abs(a + b - 1.0) < 1e-12
    assert a > b
    assert american_to_implied(-150) > 0.5


def test_none_calibration_adj_zero():
    assert movement_adjustment(0.7, 3.0, source="none") == 0.0


def test_handwritten_buckets_and_gap():
    assert movement_adjustment(0.6, 3.0, source="handwritten") == 0.03
    assert movement_adjustment(0.6, 1.5, source="handwritten") == 0.015
    assert movement_adjustment(0.6, 0.0, source="handwritten") == 0.0
    assert movement_adjustment(0.6, -1.5, source="handwritten") == -0.015
    assert movement_adjustment(0.6, -3.0, source="handwritten") == -0.03
    assert movement_adjustment(0.6, 0.75, source="handwritten") == 0.0
    assert movement_adjustment(0.6, -0.75, source="handwritten") == 0.0


def test_snapshot_at_or_before_and_missing_t72():
    kickoff = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    snaps = [
        Snapshot(
            snapshot_ts=datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc),
            home="A",
            away="B",
            h2h={"A": -110, "B": -110},
            spreads={"A": -1.0, "B": 1.0},
        ),
        Snapshot(
            snapshot_ts=datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc),
            home="A",
            away="B",
            h2h={"A": -120, "B": 100},
            spreads={"A": -2.5, "B": 2.5},
        ),
        Snapshot(
            snapshot_ts=datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc),
            home="A",
            away="B",
            h2h={"A": -200, "B": 170},
            spreads={"A": -6.0, "B": 6.0},
        ),
    ]
    current = pick_snapshot_at_or_before(snaps, min(now, kickoff))
    assert current is not None
    assert current.snapshot_ts == datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    ref = reference_snapshot(snaps, now=now, kickoff=kickoff, reference_hours=72, current=current)
    # kickoff-72h is Sept 10 17:00; no snapshot <= that
    assert ref is None or ref.snapshot_ts <= kickoff - timedelta(hours=72)
