from __future__ import annotations

from collections import defaultdict

from src.survivor.types import Game


def games_by_week(games: list[Game]) -> dict[int, list[Game]]:
    out: dict[int, list[Game]] = defaultdict(list)
    for g in games:
        out[g.week].append(g)
    return dict(out)


def team_plays_week(games: list[Game], canonical: str) -> Game | None:
    for g in games:
        if g.home_canonical == canonical or g.away_canonical == canonical:
            return g
    return None
