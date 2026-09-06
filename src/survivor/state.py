from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.survivor.types import PoolState


class StateError(ValueError):
    pass


class ConflictError(StateError):
    pass


def _committed_map(raw: Any) -> dict[int, str]:
    if not raw:
        return {}
    return {int(k): str(v) for k, v in dict(raw).items()}


def load_state(path: Path) -> PoolState:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    pool = data.get("pool") or {}
    return PoolState(
        season=int(data["season"]),
        lives_remaining=int(data["lives_remaining"]),
        used_teams=list(data.get("used_teams") or []),
        committed=_committed_map(data.get("committed")),
        notes=str(data.get("notes") or ""),
        pool_name=str(pool.get("name") or "NFL Survivor"),
        tie_rule=str(pool.get("tie_rule") or "loss"),
        last_week=int(pool.get("last_week") or 18),
    )


def dump_state(state: PoolState) -> dict[str, Any]:
    committed = {str(k): v for k, v in sorted(state.committed.items())}
    return {
        "season": state.season,
        "lives_remaining": state.lives_remaining,
        "used_teams": list(state.used_teams),
        "committed": committed,
        "notes": state.notes,
        "pool": {
            "name": state.pool_name,
            "tie_rule": state.tie_rule,
            "last_week": state.last_week,
        },
    }


def save_state(path: Path, state: PoolState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(dump_state(state), fh, sort_keys=False)


def apply_loss(state: PoolState) -> PoolState:
    state.lives_remaining = max(0, state.lives_remaining - 1)
    return state


def apply_commit(
    state: PoolState,
    team: str,
    week: int,
    *,
    loss: bool = False,
    replace: bool = False,
    overwrite: bool = True,
) -> tuple[PoolState, str]:
    """Mutate state for a recorded pick.

    Returns (state, action) where action is commit|replace|noop|loss-only.
    If overwrite is False and the week is already committed, do not change the team.
    """
    existing = state.committed.get(week)
    action = "commit"
    if existing:
        if existing == team:
            action = "noop"
        elif not overwrite:
            action = "loss-only" if loss else "noop"
        elif not replace:
            raise ConflictError(
                f"week {week} already locked to {existing}; pass replace to overwrite"
            )
        else:
            if existing in state.used_teams:
                state.used_teams = [t for t in state.used_teams if t != existing]
            state.committed[week] = team
            if team not in state.used_teams:
                state.used_teams.append(team)
            action = "replace"
    else:
        state.committed[week] = team
        if team not in state.used_teams:
            state.used_teams.append(team)
        action = "commit"

    if loss:
        apply_loss(state)
        if action == "noop":
            action = "loss-only"
    return state, action
