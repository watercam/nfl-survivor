from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.settings import canonicalize
from src.survivor.types import Game, Snapshot


def parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _status_from_espn(event: dict[str, Any]) -> str:
    status = (event.get("status") or {}).get("type") or {}
    state = str(status.get("state") or status.get("name") or "pre").lower()
    if state in {"in", "live"} or "progress" in state:
        return "in"
    if state in {"post", "final"} or "final" in state:
        return "final"
    return "scheduled"


def parse_espn_scoreboard(
    payload: dict[str, Any],
    *,
    aliases: list[dict[str, str]],
    week_fallback: int | None = None,
) -> tuple[int, list[Game], list[str]]:
    week_info = payload.get("week") or {}
    week = int(week_info.get("number") or payload.get("week_number") or week_fallback or 0)
    games: list[Game] = []
    unmapped: list[str] = []
    for event in payload.get("events") or []:
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        comp = competitions[0]
        home = away = None
        for c in comp.get("competitors") or []:
            name = ((c.get("team") or {}).get("displayName") or "").strip()
            if c.get("homeAway") == "home":
                home = name
            elif c.get("homeAway") == "away":
                away = name
        if not home or not away:
            continue
        kickoff = parse_utc(event.get("date") or comp.get("date"))
        game_id = str(event.get("id") or comp.get("id"))
        home_c = canonicalize(home, aliases)
        away_c = canonicalize(away, aliases)
        flags: list[str] = []
        if home_c is None:
            flags.append("UNMAPPED_TEAM")
            unmapped.append(home)
        if away_c is None:
            flags.append("UNMAPPED_TEAM")
            unmapped.append(away)
        games.append(
            Game(
                game_id=game_id,
                week=week,
                home=home,
                away=away,
                kickoff=kickoff,
                status=_status_from_espn(event),
                home_canonical=home_c,
                away_canonical=away_c,
                flags=flags,
            )
        )
    byes: list[str] = []
    for team in week_info.get("teamsOnBye") or payload.get("teamsOnBye") or []:
        name = team.get("displayName") if isinstance(team, dict) else str(team)
        can = canonicalize(str(name), aliases)
        if can:
            byes.append(can)
    return week, games, byes


def parse_fixture_games(
    rows: list[dict[str, Any]],
    *,
    aliases: list[dict[str, str]],
) -> list[Game]:
    games: list[Game] = []
    for row in rows:
        home = row["home"]
        away = row["away"]
        home_c = canonicalize(home, aliases)
        away_c = canonicalize(away, aliases)
        flags: list[str] = []
        if home_c is None or away_c is None:
            flags.append("UNMAPPED_TEAM")
        games.append(
            Game(
                game_id=str(row["game_id"]),
                week=int(row["week"]),
                home=home,
                away=away,
                kickoff=parse_utc(row["kickoff"]),
                status=str(row.get("status") or "scheduled"),
                home_canonical=home_c,
                away_canonical=away_c,
                flags=flags,
            )
        )
    return games


def parse_fixture_snapshots(rows: list[dict[str, Any]]) -> list[Snapshot]:
    snaps: list[Snapshot] = []
    for row in rows:
        snaps.append(
            Snapshot(
                snapshot_ts=parse_utc(row["snapshot_ts"]),
                home=row["home"],
                away=row["away"],
                game_id=str(row.get("game_id") or "") or None,
                h2h={k: int(v) for k, v in dict(row.get("h2h") or {}).items()},
                spreads={k: float(v) for k, v in dict(row.get("spreads") or {}).items()},
            )
        )
    return snaps


USER_AGENT = "nfl-survivor/0.1"


def fetch_espn_scoreboard(
    url: str,
    *,
    week: int | None = None,
    client: Any = None,
) -> dict[str, Any]:
    import httpx

    params = {"seasontype": 2}
    if week is not None:
        params["week"] = week
    owns = client is None
    http = client or httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT})
    try:
        resp = http.get(url, params=params, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns and hasattr(http, "close"):
            http.close()


def fetch_remaining_season(
    url: str,
    *,
    current_week: int,
    last_week: int,
    aliases: list[dict[str, str]],
    client: Any = None,
) -> tuple[int, list[Game]]:
    import httpx

    owns = client is None
    http = client or httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT})
    all_games: list[Game] = []
    resolved_week = current_week
    try:
        for w in range(current_week, last_week + 1):
            payload = fetch_espn_scoreboard(url, week=w, client=http)
            week_n, games, _byes = parse_espn_scoreboard(payload, aliases=aliases, week_fallback=w)
            if w == current_week:
                resolved_week = week_n or w
            all_games.extend(games)
    finally:
        if owns and hasattr(http, "close"):
            http.close()
    return resolved_week, all_games
