from src.settings import load_settings
from src.survivor.optimize import optimize
from src.survivor.payload import build_payload, load_fixture
from src.survivor.summary import build_executive_summary, week_span_label
from src.survivor.types import PathStep, PoolState
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
    assert "home prior" not in blob
    assert "Weeks 2–18 have no Pinnacle price" not in blob
    assert len(bullets) >= 4
    primary = result["primary"]
    assert primary.ml == -355
    assert primary.line_source == "pinnacle"
    ratings_step = next(s for s in result["projected_path"] if s.source == "ratings" and s.team)
    assert ratings_step.line_source == "ratings"
    assert ratings_step.ml is not None
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
    assert payload["model"]["future_ratings"] >= 1
    assert payload["model"]["future_market"] >= 1


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


def test_week_span_skips_priced_gaps():
    assert week_span_label([2, 3, 4, 7]) == "Weeks 2–4, 7"
    assert week_span_label([8]) == "Week 8"


def test_mixed_market_ratings_summary_does_not_blanket_prior():
    _settings, _now, week, state, result = _optimize()
    result = {
        **result,
        "projected_path": [
            PathStep(week=1, team="Buffalo Bills", p_win=0.78, source="market", line_source="pinnacle"),
            PathStep(week=2, team="Atlanta Falcons", p_win=0.58, source="prior", line_source="imputed"),
            PathStep(week=8, team="Los Angeles Chargers", p_win=0.70, source="ratings", line_source="ratings"),
            PathStep(week=15, team="Kansas City Chiefs", p_win=0.90, source="market", line_source="pinnacle"),
            PathStep(week=18, team="Chicago Bears", p_win=0.58, source="prior", line_source="imputed"),
        ],
    }
    bullets = build_executive_summary(week=week, state=state, result=result)
    blob = " ".join(bullets)
    assert "Weeks 2–18 have no Pinnacle price" not in blob
    prior_bullet = next(item for item in bullets if "home prior" in item)
    assert "Week 2" in prior_bullet or "Weeks 2" in prior_bullet
    assert "18" in prior_bullet
    assert "Week 8" not in prior_bullet
    assert "–8" not in prior_bullet
    assert "15" not in prior_bullet.replace("58/42", "")
