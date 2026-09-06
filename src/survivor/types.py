from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Literal

Source = Literal["market", "prior"]


@dataclass
class Game:
    game_id: str
    week: int
    home: str
    away: str
    kickoff: datetime
    status: str = "scheduled"
    home_canonical: str | None = None
    away_canonical: str | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def started(self) -> bool:
        return self.status in {"in", "final", "post"} or self.status.startswith("STATUS_")


@dataclass
class Snapshot:
    snapshot_ts: datetime
    home: str
    away: str
    game_id: str | None = None
    h2h: dict[str, int] = field(default_factory=dict)
    spreads: dict[str, float] = field(default_factory=dict)


@dataclass
class ScoredSide:
    team: str
    opponent: str
    is_home: bool
    week: int
    game_id: str
    kickoff: datetime
    p_current: float | None
    spread_move: float
    adj: float
    p_final: float
    source: Source
    flags: list[str] = field(default_factory=list)
    survive_p: float | None = None
    locked: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "team": self.team,
            "opponent": self.opponent,
            "is_home": self.is_home,
            "kickoff": self.kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "p_current": self.p_current,
            "spread_move": self.spread_move,
            "adj": self.adj,
            "p_final": self.p_final,
            "survive_p": self.survive_p,
            "source": self.source,
            "flags": list(self.flags),
            "game_id": self.game_id,
            "locked": self.locked,
        }


@dataclass
class PathStep:
    week: int
    team: str
    p_win: float
    source: Source
    opponent: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PoolState:
    season: int
    lives_remaining: int
    used_teams: list[str]
    committed: dict[int, str]
    notes: str
    pool_name: str
    tie_rule: str
    last_week: int
