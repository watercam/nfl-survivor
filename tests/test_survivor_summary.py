from src.settings import load_settings
from src.survivor.optimize import optimize
from src.survivor.payload import build_payload, load_fixture
from src.survivor.summary import build_executive_summary
from src.survivor.types import PoolState
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "survivor_week.json"


def _state(**kwargs) -> PoolState:
    base = dict(
        season=2026,
        lives_remaining=2,
        used_teams=[],
        committed={},
        notes="",
        pool_name="NFL Survivor",
        tie_rule="loss",
        last_week=15,
    )
    base.update(kwargs)
    return PoolState(**base)


def _optimize(**state_kw):
    settings = load_settings()
    now, week, last_week, games, snapshots = load_fixture(FIXTURE, settings.aliases)
    state = _state(last_week=last_week, **state_kw)
    result = optimize(
        current_week=week,
        games=games,
        snapshots=snapshots,
        now=now,
        settings=settings,
        state=state,
        aliases=settings.aliases,
    )
    return settings, now, week, state, result


def test_save_for_later_summary_and_pinnacle_line():
    settings, now, week, state, result = _optimize()
    bullets = build_executive_summary(week=week, state=state, result=result)
    blob = " ".join(bullets)
    assert "Buffalo Bills" in blob
    assert "Kansas City Chiefs" in blob
    assert "Season survival" in blob
    assert "2 lives left" in blob
    assert "home prior" in blob
    assert len(bullets) >= 4
    primary = result["primary"]
    assert primary.ml == -355
    assert primary.line_source == "pinnacle"
    prior_step = next(s for s in result["projected_path"] if s.source == "prior" and s.team)
    assert prior_step.line_source == "imputed"
    assert prior_step.ml is not None
    payload = build_payload(
        week=week,
        now=now,
        settings=settings,
        state=state,
        result=result,
        previous=None,
        aliases=settings.aliases,
    )
    assert payload["executive_summary"] == bullets
    assert payload["primary"]["ml"] == -355
    assert payload["primary"]["line_source"] == "pinnacle"


def test_eliminated_summary():
    _settings, _now, week, state, result = _optimize(lives_remaining=0)
    bullets = build_executive_summary(week=week, state=state, result=result)
    assert bullets == ["No recommend — you are out of lives."]


def test_locked_and_favorite_aligned_summary():
    settings, now, week, state, result = _optimize(used_teams=["Buffalo Bills"])
    # Bills used → engine should not pick them; just check locked copy when committed matches primary
    primary = result["primary"]
    assert primary is not None
    state.committed[week] = primary.team
    bullets = build_executive_summary(week=week, state=state, result=result)
    assert any(f"Week {week} is locked on {primary.team}" in item for item in bullets)
