from __future__ import annotations

from src.survivor.types import PathStep, PoolState, ScoredSide

CLOSE_SURVIVE = 0.01


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    pct = 100.0 * value
    if pct >= 10:
        return f"{pct:.0f}%"
    if pct >= 1:
        return f"{pct:.1f}%"
    return f"{pct:.2f}%"


def build_executive_summary(
    *,
    week: int,
    state: PoolState,
    result: dict,
) -> list[str]:
    primary: ScoredSide | None = result.get("primary")
    greedy: ScoredSide | None = result.get("greedy_this_week")
    status = result.get("status")
    alts: list[ScoredSide] = list(result.get("alternatives") or [])
    path: list[PathStep] = list(result.get("projected_path") or [])

    if status == "eliminated" or state.lives_remaining <= 0:
        return ["No recommend — you are out of lives."]
    if primary is None:
        return [
            f"No legal pick this week (week {week}): unused teams have kicked off "
            "or have no moneyline."
        ]

    bullets: list[str] = []
    locked = state.committed.get(week)
    if locked:
        if locked == primary.team:
            bullets.append(f"Week {week} is locked on {primary.team}.")
        else:
            bullets.append(
                f"Week {week} is locked on {locked}; the engine still ranks {primary.team} first."
            )

    if greedy is not None and greedy.team != primary.team:
        bullets.append(
            f"Take {primary.team} this week ({_pct(primary.p_final)} to win)."
        )
        bullets.append(
            f"Season survival ({_pct(primary.survive_p)}) beats using {greedy.team} now "
            f"({_pct(greedy.p_final)} this week, {_pct(greedy.survive_p)} survive)."
        )
        later = next((step for step in path if step.team == greedy.team), None)
        if later is not None:
            vs = f" vs {later.opponent}" if later.opponent else ""
            bullets.append(
                f"{greedy.team} is reserved for week {later.week}{vs} "
                f"({later.source}, {_pct(later.p_win)})."
            )
        else:
            bullets.append(f"{greedy.team} is saved for a later week.")
    else:
        bullets.append(f"Take {primary.team} ({_pct(primary.p_final)} this week).")
        bullets.append(
            f"They are both the strongest this-week win and the best season-survival pick "
            f"({_pct(primary.survive_p)})."
        )

    others = [side for side in alts if side.team != primary.team]
    if (
        others
        and primary.survive_p is not None
        and others[0].survive_p is not None
        and 0 <= (primary.survive_p - others[0].survive_p) <= CLOSE_SURVIVE
        and (greedy is None or others[0].team != greedy.team)
    ):
        bullets.append(
            f"Close second: {others[0].team} at {_pct(others[0].survive_p)} season survive."
        )

    if state.lives_remaining == 1:
        bullets.append("One life left — a loss this week ends the pool.")
    elif (
        state.lives_remaining >= 2
        and greedy is not None
        and greedy.team != primary.team
    ):
        bullets.append(
            f"{state.lives_remaining} lives left, so a slightly weaker this-week win "
            "can be spent to keep a later hammer."
        )

    prior_steps = [step for step in path if step.source == "prior" and step.team]
    if prior_steps:
        first = prior_steps[0].week
        last = prior_steps[-1].week
        span = f"Week {first}" if first == last else f"Weeks {first}–{last}"
        bullets.append(
            f"{span} have no Pinnacle price yet, so the path uses the home prior (58/42)."
        )
    if any(not step.team for step in path):
        bullets.append("At least one later week has no unused team left (starve).")

    return bullets
