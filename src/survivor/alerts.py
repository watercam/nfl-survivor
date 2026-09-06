from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.survivor.types import ScoredSide

NY = ZoneInfo("America/New_York")


def collect_alerts(
    *,
    week: int,
    now: datetime,
    primary: ScoredSide | None,
    previous: dict | None,
    survive_p: float | None,
    locked_team: str | None,
    status: str,
    flags: list[str],
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    prev_week = None if not previous else previous.get("week")
    if previous is None or prev_week != week:
        alerts.append({"kind": "new_week_slate", "detail": "new week or no prior snapshot"})
    prev_primary = None
    prev_survive = None
    if previous and prev_week == week:
        prev_primary = ((previous.get("primary") or {}) or {}).get("team")
        prev_survive = ((previous.get("primary") or {}) or {}).get("survive_p")
    if primary and prev_primary and primary.team != prev_primary:
        alerts.append({"kind": "pick_change", "detail": f"{prev_primary} → {primary.team}"})
    if (
        primary
        and prev_survive is not None
        and primary.survive_p is not None
        and (prev_survive - primary.survive_p) >= 0.03
    ):
        alerts.append({"kind": "survive_drop", "detail": f"{prev_survive:.3f} → {primary.survive_p:.3f}"})
    watch = primary
    if watch and now + timedelta(hours=6) >= watch.kickoff > now:
        alerts.append({"kind": "kickoff_soon", "detail": watch.team})
    if primary:
        kickoff_ny = primary.kickoff.astimezone(NY)
        now_ny = now.astimezone(NY)
        if kickoff_ny.weekday() == 3:  # Thursday
            wed_noon = kickoff_ny.replace(hour=12, minute=0, second=0, microsecond=0)
            # Wednesday of that week
            while wed_noon.weekday() != 2:
                wed_noon = wed_noon - timedelta(days=1)
            wed_noon = wed_noon.replace(hour=12, minute=0, second=0, microsecond=0)
            if now_ny >= wed_noon:
                alerts.append({"kind": "thursday_risk", "detail": primary.team})
    if locked_team and primary and locked_team != primary.team:
        alerts.append({"kind": "locked_diverges", "detail": f"locked {locked_team} vs model {primary.team}"})
    if status == "eliminated":
        alerts.append({"kind": "eliminated", "detail": "lives_remaining is 0"})
    if "FUTURE_STARVE" in flags:
        alerts.append({"kind": "future_starve", "detail": "a future week has no legal team"})
    return alerts
