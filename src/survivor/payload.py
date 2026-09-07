from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from src.settings import Settings, abbr_for
from src.survivor.alerts import collect_alerts
from src.survivor.optimize import optimize
from src.survivor.slate import parse_fixture_games, parse_fixture_snapshots, parse_utc
from src.survivor.slack import format_success, post_webhook
from src.survivor.summary import build_executive_summary
from src.survivor.types import PoolState, ScoredSide


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_previous(dashboard_url: str) -> dict[str, Any] | None:
    if not dashboard_url:
        return None
    url = urljoin(dashboard_url.rstrip("/") + "/", "recommendations.json")
    try:
        resp = httpx.get(url, timeout=15.0, headers={"User-Agent": "nfl-survivor/0.1"})
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def print_table(
    *,
    week: int,
    state: PoolState,
    status: str,
    calibration: str,
    ranked: list[ScoredSide],
    aliases: list[dict[str, str]],
) -> None:
    print(f"week: {week}")
    print(f"lives: {state.lives_remaining}")
    print(f"used: {len(state.used_teams)}")
    print(f"status: {status}")
    print(f"calibration: {calibration}")
    print()
    header = f"{'pick':<8}{'opponent':<18}{'kickoff':<22}{'p_week':<9}{'survive_p':<11}{'source':<9}flags"
    print(header)
    for side in ranked[:8]:
        pick = abbr_for(side.team, aliases)
        opp = abbr_for(side.opponent, aliases)
        p_week = f"{side.p_final:.2f}"
        surv = f"{side.survive_p:.2f}" if side.survive_p is not None else "-"
        flags = ",".join(side.flags) if side.flags else "-"
        print(
            f"{pick:<8}{opp:<18}{iso(side.kickoff):<22}{p_week:<9}{surv:<11}{side.source:<9}{flags}"
        )


def build_payload(
    *,
    week: int,
    now: datetime,
    settings: Settings,
    state: PoolState,
    result: dict[str, Any],
    previous: dict[str, Any] | None,
    aliases: list[dict[str, str]],
) -> dict[str, Any]:
    primary: ScoredSide | None = result["primary"]
    greedy = result["greedy_this_week"]
    flags = list(primary.flags) if primary else []
    notes = state.notes or None
    if previous and previous.get("week") == week and previous.get("notes") not in (None, ""):
        notes = previous.get("notes")
    alerts = collect_alerts(
        week=week,
        now=now,
        primary=primary,
        previous=previous,
        survive_p=primary.survive_p if primary else None,
        locked_team=state.committed.get(week),
        status=result["status"],
        flags=flags,
    )
    greedy_payload = None
    if greedy:
        greedy_payload = {"team": greedy.team, "p_final": greedy.p_final}
    ratings = dict(result.get("ratings") or {})
    ranked_ratings = sorted(ratings.items(), key=lambda item: item[1], reverse=True)
    future_steps = list(result.get("projected_path") or [])[1:]
    model = {
        "top": [{"team": team, "rating": rating} for team, rating in ranked_ratings[:5]],
        "bottom": [{"team": team, "rating": rating} for team, rating in ranked_ratings[-5:][::-1]],
        "future_market": sum(1 for step in future_steps if step.source == "market"),
        "future_ratings": sum(1 for step in future_steps if step.source == "ratings"),
        "future_prior": sum(1 for step in future_steps if step.source == "prior"),
    }
    return {
        "week": week,
        "season": state.season,
        "lives_remaining": state.lives_remaining,
        "status": result["status"],
        "calibration": settings.calibration.source,
        "generated_at": iso(now),
        "used_teams": list(state.used_teams),
        "committed_this_week": state.committed.get(week),
        "primary": None if result["status"] == "eliminated" else (primary.to_payload() if primary else None),
        "greedy_this_week": greedy_payload,
        "alternatives": [s.to_payload() for s in result["alternatives"]],
        "projected_path": [p.to_payload() for p in result["projected_path"]],
        "slate": [
            {
                "game_id": s.game_id,
                "team": s.team,
                "opponent": s.opponent,
                "p_final": s.p_final,
                "survive_p": s.survive_p,
                "kickoff": iso(s.kickoff),
            }
            for s in result["all_ranked"]
        ],
        "alerts": alerts,
        "notes": notes,
        "record_pick_url": settings.record_pick_url(),
        "executive_summary": build_executive_summary(week=week, state=state, result=result),
        "model": model,
    }


def load_fixture(path: Path, aliases: list[dict[str, str]]):
    data = json.loads(path.read_text(encoding="utf-8"))
    now = parse_utc(data["now"])
    week = int(data["week"])
    last_week = int(data.get("last_week") or 18)
    games = parse_fixture_games(data.get("games") or [], aliases=aliases)
    snapshots = parse_fixture_snapshots(data.get("snapshots") or [])
    return now, week, last_week, games, snapshots
