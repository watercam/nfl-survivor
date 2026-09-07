from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.survivor.types import Snapshot


def american_to_implied(odds: int | float) -> float:
    o = float(odds)
    if o == 0:
        raise ValueError("american odds cannot be 0")
    if o < 0:
        return abs(o) / (abs(o) + 100.0)
    return 100.0 / (o + 100.0)


def no_vig_pair(odds_a: int | float, odds_b: int | float) -> tuple[float, float]:
    ia = american_to_implied(odds_a)
    ib = american_to_implied(odds_b)
    total = ia + ib
    if total <= 0:
        raise ValueError("implied probabilities must be positive")
    return ia / total, ib / total


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def probability_to_american(p: float, *, lo: float = 0.01, hi: float = 0.99) -> int:
    p = clamp(float(p), lo, hi)
    if p >= 0.5:
        return int(round(-100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


def format_american(odds: int | None) -> str:
    if odds is None:
        return "—"
    n = int(odds)
    if n > 0:
        return f"+{n}"
    return str(n)


def pick_snapshot_at_or_before(
    snapshots: list[Snapshot],
    cutoff: datetime,
) -> Snapshot | None:
    eligible = [s for s in snapshots if s.snapshot_ts <= cutoff]
    if not eligible:
        return None
    return max(eligible, key=lambda s: s.snapshot_ts)


def current_snapshot_cutoff(now: datetime, kickoff: datetime) -> datetime:
    return min(now, kickoff)


def reference_snapshot(
    snapshots: list[Snapshot],
    *,
    now: datetime,
    kickoff: datetime,
    reference_hours: int,
    current: Snapshot | None = None,
) -> Snapshot | None:
    current = current or pick_snapshot_at_or_before(
        snapshots, current_snapshot_cutoff(now, kickoff)
    )
    if current is None:
        return None
    t72 = kickoff - timedelta(hours=reference_hours)
    if now < t72:
        return None
    cutoff = min(t72, current.snapshot_ts)
    return pick_snapshot_at_or_before(snapshots, cutoff)


def spread_move_for_team(
    *,
    team: str,
    current: Snapshot,
    reference: Snapshot | None,
) -> tuple[float, list[str]]:
    flags: list[str] = []
    if reference is None:
        flags.append("REFERENCE_MISSING")
        return 0.0, flags
    cur = current.spreads.get(team)
    ref = reference.spreads.get(team)
    if cur is None or ref is None:
        flags.append("REFERENCE_MISSING")
        return 0.0, flags
    return float(ref) - float(cur), flags
