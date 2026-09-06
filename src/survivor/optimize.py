from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from src.settings import Settings, names_for_canonical
from src.survivor.calibration import movement_adjustment
from src.survivor.odds import match_snapshots
from src.survivor.probability import (
    clamp,
    current_snapshot_cutoff,
    no_vig_pair,
    pick_snapshot_at_or_before,
    reference_snapshot,
    spread_move_for_team,
)
from src.survivor.schedule import games_by_week
from src.survivor.types import Game, PoolState, ScoredSide, Snapshot, PathStep


def survive_probability(path: list[float], lives: int) -> float:
    n = len(path)

    @lru_cache(maxsize=None)
    def S(i: int, lives_left: int) -> float:
        if lives_left <= 0:
            return 0.0
        if i >= n:
            return 1.0
        p = path[i]
        return p * S(i + 1, lives_left) + (1.0 - p) * S(i + 1, lives_left - 1)

    return S(0, lives)


def _odds_for_team(
    snapshot: Snapshot,
    team: str,
    opponent: str,
    aliases: list[dict[str, str]] | None = None,
) -> tuple[int, int] | None:
    team_names = names_for_canonical(team, aliases or []) or [team]
    opp_names = names_for_canonical(opponent, aliases or []) or [opponent]
    if team not in team_names:
        team_names.append(team)
    if opponent not in opp_names:
        opp_names.append(opponent)
    a = next((snapshot.h2h[n] for n in team_names if n in snapshot.h2h), None)
    b = next((snapshot.h2h[n] for n in opp_names if n in snapshot.h2h), None)
    if a is None or b is None:
        return None
    return int(a), int(b)


def score_side(
    *,
    game: Game,
    team: str,
    opponent: str,
    is_home: bool,
    snapshots: list[Snapshot],
    now: datetime,
    settings: Settings,
    aliases: list[dict[str, str]],
    this_week: bool,
) -> ScoredSide | None:
    flags = list(game.flags)
    if team is None or opponent is None:
        flags.append("UNMAPPED_TEAM")
        return None
    if "UNMAPPED_TEAM" in flags and (game.home_canonical is None or game.away_canonical is None):
        return None

    matched = match_snapshots(
        snapshots,
        home=game.home,
        away=game.away,
        aliases=aliases,
        game_id=game.game_id,
    )
    if this_week:
        current = pick_snapshot_at_or_before(
            matched, current_snapshot_cutoff(now, game.kickoff)
        )
        if current is None:
            flags.append("NO_CURRENT_ML")
            return None
        pair = _odds_for_team(current, team, opponent, aliases)
        if pair is None:
            flags.append("NO_CURRENT_ML")
            return None
        p_current, _ = no_vig_pair(pair[0], pair[1])
        ref = reference_snapshot(
            matched,
            now=now,
            kickoff=game.kickoff,
            reference_hours=settings.reference_hours,
            current=current,
        )
        spread_keys = names_for_canonical(team, aliases) + [game.home if is_home else game.away]
        spread_team = next((k for k in spread_keys if k in current.spreads), team)
        move, move_flags = spread_move_for_team(team=spread_team, current=current, reference=ref)
        flags.extend(move_flags)
        adj = movement_adjustment(
            p_current,
            move,
            source=settings.calibration.source,
            matrix_csv=settings.calibration.matrix_csv,
        )
        p_final = clamp(p_current + adj, settings.calibration.clamp_min, settings.calibration.clamp_max)
        return ScoredSide(
            team=team,
            opponent=opponent,
            is_home=is_home,
            week=game.week,
            game_id=game.game_id,
            kickoff=game.kickoff,
            p_current=p_current,
            spread_move=move,
            adj=adj,
            p_final=p_final,
            source="market",
            flags=flags,
        )

    # Future week: current-payload h2h only (no T-72)
    current = pick_snapshot_at_or_before(matched, now) if matched else None
    if current is not None:
        pair = _odds_for_team(current, team, opponent, aliases)
        if pair is not None:
            p_current, _ = no_vig_pair(pair[0], pair[1])
            p_final = clamp(p_current, settings.calibration.clamp_min, settings.calibration.clamp_max)
            return ScoredSide(
                team=team,
                opponent=opponent,
                is_home=is_home,
                week=game.week,
                game_id=game.game_id,
                kickoff=game.kickoff,
                p_current=p_current,
                spread_move=0.0,
                adj=0.0,
                p_final=p_final,
                source="market",
                flags=flags,
            )
    flags.append("PRIOR_NO_MARKET")
    p = settings.home_prior if is_home else (1.0 - settings.home_prior)
    return ScoredSide(
        team=team,
        opponent=opponent,
        is_home=is_home,
        week=game.week,
        game_id=game.game_id,
        kickoff=game.kickoff,
        p_current=None,
        spread_move=0.0,
        adj=0.0,
        p_final=p,
        source="prior",
        flags=flags,
    )


def score_week(
    games: list[Game],
    *,
    snapshots: list[Snapshot],
    now: datetime,
    settings: Settings,
    aliases: list[dict[str, str]],
    this_week: bool,
    used_teams: set[str],
    drop_started: bool,
) -> list[ScoredSide]:
    sides: list[ScoredSide] = []
    for game in games:
        if drop_started and now >= game.kickoff:
            continue
        if game.status in {"in", "final"}:
            if drop_started:
                continue
        pairs = [
            (game.away_canonical, game.home_canonical, False),
            (game.home_canonical, game.away_canonical, True),
        ]
        for team, opp, is_home in pairs:
            if team is None or opp is None:
                continue
            if team in used_teams:
                continue
            scored = score_side(
                game=game,
                team=team,
                opponent=opp,
                is_home=is_home,
                snapshots=snapshots,
                now=now,
                settings=settings,
                aliases=aliases,
                this_week=this_week,
            )
            if scored is None:
                continue
            sides.append(scored)
    return sides


def _greedy_key(side: ScoredSide) -> tuple:
    p_cur = side.p_current if side.p_current is not None else -1.0
    return (side.p_final, p_cur, 1 if side.is_home else 0, side.game_id)


def greedy_pick(sides: list[ScoredSide]) -> ScoredSide | None:
    if not sides:
        return None
    return max(sides, key=_greedy_key)


def future_path(
    *,
    start_week: int,
    last_week: int,
    by_week: dict[int, list[Game]],
    snapshots: list[Snapshot],
    now: datetime,
    settings: Settings,
    aliases: list[dict[str, str]],
    used: set[str],
) -> tuple[list[PathStep], list[str]]:
    flags: list[str] = []
    steps: list[PathStep] = []
    used = set(used)
    for w in range(start_week, last_week + 1):
        games = by_week.get(w) or []
        sides = score_week(
            games,
            snapshots=snapshots,
            now=now,
            settings=settings,
            aliases=aliases,
            this_week=False,
            used_teams=used,
            drop_started=False,
        )
        pick = greedy_pick(sides)
        if pick is None:
            flags.append("FUTURE_STARVE")
            steps.append(PathStep(week=w, team="", p_win=0.0, source="prior"))
            continue
        steps.append(
            PathStep(
                week=w,
                team=pick.team,
                p_win=pick.p_final,
                source=pick.source,
                opponent=pick.opponent,
            )
        )
        used.add(pick.team)
    return steps, flags


def _recommend_key(side: ScoredSide) -> tuple:
    p_cur = side.p_current if side.p_current is not None else -1.0
    # earlier kickoff wins: negate timestamp
    return (
        side.survive_p or 0.0,
        side.p_final,
        p_cur,
        -side.kickoff.timestamp(),
        side.game_id,
    )


def optimize(
    *,
    current_week: int,
    games: list[Game],
    snapshots: list[Snapshot],
    now: datetime,
    settings: Settings,
    state: PoolState,
    aliases: list[dict[str, str]],
) -> dict:
    last_week = min(state.last_week, settings.last_week)
    by_week = games_by_week(games)
    this_games = by_week.get(current_week) or []
    used = set(state.used_teams)
    eliminated = state.lives_remaining <= 0
    legal = score_week(
        this_games,
        snapshots=snapshots,
        now=now,
        settings=settings,
        aliases=aliases,
        this_week=True,
        used_teams=used,
        drop_started=True,
    )
    ranked: list[ScoredSide] = []
    for side in legal:
        steps, extra = future_path(
            start_week=current_week + 1,
            last_week=last_week,
            by_week=by_week,
            snapshots=snapshots,
            now=now,
            settings=settings,
            aliases=aliases,
            used=used | {side.team},
        )
        path = [side.p_final] + [s.p_win for s in steps]
        side.survive_p = survive_probability(path, state.lives_remaining)
        side.flags = list(dict.fromkeys(side.flags + extra))
        ranked.append(side)

    ranked.sort(key=_recommend_key, reverse=True)
    committed_team = state.committed.get(current_week)
    for side in ranked:
        if committed_team and side.team == committed_team:
            side.locked = True

    greedy = max(ranked, key=lambda s: (s.p_final, s.p_current or -1.0, -s.kickoff.timestamp(), s.game_id)) if ranked else None
    primary = None if eliminated or not ranked else ranked[0]
    projected: list[PathStep] = []
    if primary is not None:
        rest, _ = future_path(
            start_week=current_week + 1,
            last_week=last_week,
            by_week=by_week,
            snapshots=snapshots,
            now=now,
            settings=settings,
            aliases=aliases,
            used=used | {primary.team},
        )
        projected = [
            PathStep(
                week=current_week,
                team=primary.team,
                p_win=primary.p_final,
                source=primary.source,
                opponent=primary.opponent,
            )
        ] + rest

    return {
        "status": "eliminated" if eliminated else "active",
        "primary": primary,
        "alternatives": ranked[:5],
        "all_ranked": ranked,
        "greedy_this_week": greedy,
        "projected_path": projected,
        "legal": legal,
    }
