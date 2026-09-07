from __future__ import annotations

import math

from src.settings import canonicalize, names_for_canonical
from src.survivor.probability import clamp, no_vig_pair
from src.survivor.types import Snapshot

# NFL rule of thumb: ~2.4 points of spread per logit of win probability.
SPREAD_LOGIT_POINTS = 2.4
_PROB_EPS = 1e-6


def logit(p: float) -> float:
    p = clamp(float(p), _PROB_EPS, 1.0 - _PROB_EPS)
    return math.log(p / (1.0 - p))


def sigmoid(x: float) -> float:
    x = float(x)
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def spread_to_p(home_spread: float, *, pts_per_logit: float = SPREAD_LOGIT_POINTS) -> float:
    """Home spread is negative when the home team is favored."""
    return sigmoid(-float(home_spread) / pts_per_logit)


def predict_p(
    home: str,
    away: str,
    *,
    is_home: bool,
    ratings: dict[str, float],
    hfa: float,
) -> float:
    p_home = sigmoid(ratings.get(home, 0.0) - ratings.get(away, 0.0) + logit(hfa))
    return p_home if is_home else 1.0 - p_home


def _lookup_names(canonical: str, raw: str, aliases: list[dict[str, str]]) -> list[str]:
    names = list(names_for_canonical(canonical, aliases) or [canonical])
    for extra in (canonical, raw):
        if extra and extra not in names:
            names.append(extra)
    return names


def p_home_from_h2h(snapshot: Snapshot, aliases: list[dict[str, str]]) -> float | None:
    if not snapshot.h2h:
        return None
    home = canonicalize(snapshot.home, aliases) or snapshot.home
    away = canonicalize(snapshot.away, aliases) or snapshot.away
    home_odds = next((snapshot.h2h[n] for n in _lookup_names(home, snapshot.home, aliases) if n in snapshot.h2h), None)
    away_odds = next((snapshot.h2h[n] for n in _lookup_names(away, snapshot.away, aliases) if n in snapshot.h2h), None)
    if home_odds is None or away_odds is None:
        return None
    p_home, _ = no_vig_pair(home_odds, away_odds)
    return p_home


def home_spread(snapshot: Snapshot, aliases: list[dict[str, str]]) -> float | None:
    if not snapshot.spreads:
        return None
    home = canonicalize(snapshot.home, aliases) or snapshot.home
    return next(
        (snapshot.spreads[n] for n in _lookup_names(home, snapshot.home, aliases) if n in snapshot.spreads),
        None,
    )


def _latest_by_game(snapshots: list[Snapshot], aliases: list[dict[str, str]]) -> list[Snapshot]:
    latest: dict[object, Snapshot] = {}
    for snap in snapshots:
        home = canonicalize(snap.home, aliases) or snap.home
        away = canonicalize(snap.away, aliases) or snap.away
        key: object = snap.game_id or (home, away)
        prev = latest.get(key)
        if prev is None or snap.snapshot_ts >= prev.snapshot_ts:
            latest[key] = snap
    return list(latest.values())


def market_observations(
    snapshots: list[Snapshot],
    aliases: list[dict[str, str]],
) -> list[tuple[str, str, float]]:
    rows: list[tuple[str, str, float, datetime]] = []
    for snap in _latest_by_game(snapshots, aliases):
        home = canonicalize(snap.home, aliases) or snap.home
        away = canonicalize(snap.away, aliases) or snap.away
        if not home or not away or home == away:
            continue
        p = p_home_from_h2h(snap, aliases)
        if p is None:
            spread = home_spread(snap, aliases)
            if spread is None:
                continue
            p = spread_to_p(spread)
        rows.append((home, away, p, snap.snapshot_ts))
    return [(home, away, p) for home, away, p, _ in rows]


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    n = len(rhs)
    if n == 0 or any(len(row) != n for row in matrix):
        return None
    a = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        diag = a[col][col]
        for j in range(col, n + 1):
            a[col][j] /= diag
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col]
            if factor == 0:
                continue
            for j in range(col, n + 1):
                a[row][j] -= factor * a[col][j]
    return [a[i][n] for i in range(n)]


def fit_ratings(
    snapshots: list[Snapshot],
    aliases: list[dict[str, str]],
    *,
    hfa: float,
    ridge: float,
) -> dict[str, float] | None:
    games = market_observations(snapshots, aliases)
    if not games:
        return None
    teams: list[str] = []
    index: dict[str, int] = {}
    for home, away, _p in games:
        for team in (home, away):
            if team not in index:
                index[team] = len(teams)
                teams.append(team)
    n = len(teams)
    xtx = [[0.0] * n for _ in range(n)]
    xty = [0.0] * n
    hfa_logit = logit(hfa)
    for home, away, p_home in games:
        i = index[home]
        j = index[away]
        y = logit(p_home) - hfa_logit
        # Design row: +1 home, -1 away.
        xtx[i][i] += 1.0
        xtx[j][j] += 1.0
        xtx[i][j] -= 1.0
        xtx[j][i] -= 1.0
        xty[i] += y
        xty[j] -= y
    lam = float(ridge)
    for i in range(n):
        xtx[i][i] += lam
        for j in range(n):
            # μ 1 1ᵀ keeps ∑r ≈ 0 on short slates (16 games, 32 teams).
            xtx[i][j] += lam
    solved = _solve(xtx, xty)
    if solved is None:
        return None
    return {team: solved[index[team]] for team in teams}
