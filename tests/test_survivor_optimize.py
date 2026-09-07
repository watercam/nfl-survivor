from datetime import datetime, timezone

from src.settings import load_settings
from src.survivor.optimize import optimize, survive_probability
from src.survivor.payload import load_fixture
from src.survivor.slate import parse_fixture_games, parse_utc
from src.survivor.types import Game, PoolState
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


def test_thirty_two_franchises():
    settings = load_settings()
    names = [row["canonical"] for row in settings.aliases]
    assert len(names) == 32
    assert len(set(names)) == 32
    assert "Kansas City Chiefs" in names


def test_dp_lives_and_starve():
    two = survive_probability([0.8, 0.8], 2)
    one = survive_probability([0.8, 0.8], 1)
    assert one < two
    assert survive_probability([0.0], 1) == 0.0
    assert survive_probability([0.0, 0.9], 1) == 0.0
    assert survive_probability([0.0], 2) == 1.0


def test_lookahead_save_prefers_bills_not_chiefs():
    settings = load_settings()
    now, week, last_week, games, snapshots = load_fixture(FIXTURE, settings.aliases)
    state = _state(last_week=last_week)
    result = optimize(
        current_week=week,
        games=games,
        snapshots=snapshots,
        now=now,
        settings=settings,
        state=state,
        aliases=settings.aliases,
    )
    assert result["primary"] is not None
    assert result["primary"].team == "Buffalo Bills"
    greedy = result["greedy_this_week"]
    assert greedy is not None
    assert greedy.team == "Kansas City Chiefs"
    assert result["primary"].team != greedy.team


def test_used_team_not_legal():
    settings = load_settings()
    now, week, last_week, games, snapshots = load_fixture(FIXTURE, settings.aliases)
    state = _state(last_week=last_week, used_teams=["Buffalo Bills"])
    result = optimize(
        current_week=week,
        games=games,
        snapshots=snapshots,
        now=now,
        settings=settings,
        state=state,
        aliases=settings.aliases,
    )
    teams = {s.team for s in result["legal"]}
    assert "Buffalo Bills" not in teams


def test_bye_absent_from_slate():
    settings = load_settings()
    now, week, last_week, games, snapshots = load_fixture(FIXTURE, settings.aliases)
    state = _state(last_week=last_week)
    result = optimize(
        current_week=week,
        games=games,
        snapshots=snapshots,
        now=now,
        settings=settings,
        state=state,
        aliases=settings.aliases,
    )
    teams = {s.team for s in result["legal"]}
    assert "Miami Dolphins" not in teams  # not on week 1 slate


def test_kickoff_lock_drops_both_sides():
    settings = load_settings()
    now, week, last_week, games, snapshots = load_fixture(FIXTURE, settings.aliases)
    state = _state(last_week=last_week)
    result = optimize(
        current_week=week,
        games=games,
        snapshots=snapshots,
        now=now,
        settings=settings,
        state=state,
        aliases=settings.aliases,
    )
    teams = {s.team for s in result["legal"]}
    assert "Seattle Seahawks" not in teams
    assert "San Francisco 49ers" not in teams


def test_unmapped_espn_name_skipped():
    settings = load_settings()
    games = parse_fixture_games(
        [
            {
                "game_id": "x",
                "week": 1,
                "home": "Springfield Atoms",
                "away": "Buffalo Bills",
                "kickoff": "2026-09-13T17:00:00Z",
            }
        ],
        aliases=settings.aliases,
    )
    assert games[0].home_canonical is None
    assert "UNMAPPED_TEAM" in games[0].flags
    now = parse_utc("2026-09-08T16:00:00Z")
    result = optimize(
        current_week=1,
        games=games,
        snapshots=[],
        now=now,
        settings=settings,
        state=_state(),
        aliases=settings.aliases,
    )
    teams = {s.team for s in result["legal"]}
    assert "Springfield Atoms" not in teams
    assert "Buffalo Bills" not in teams  # opponent unmapped → skip both (no canonical opp)


def test_this_week_no_ml_skipped():
    settings = load_settings()
    now = datetime(2026, 9, 8, 16, tzinfo=timezone.utc)
    game = Game(
        game_id="noline",
        week=1,
        home="Buffalo Bills",
        away="Arizona Cardinals",
        kickoff=datetime(2026, 9, 13, 17, tzinfo=timezone.utc),
        home_canonical="Buffalo Bills",
        away_canonical="Arizona Cardinals",
    )
    result = optimize(
        current_week=1,
        games=[game],
        snapshots=[],
        now=now,
        settings=settings,
        state=_state(),
        aliases=settings.aliases,
    )
    assert result["legal"] == []


def test_future_unpriced_uses_ratings():
    settings = load_settings()
    now, week, last_week, games, snapshots = load_fixture(FIXTURE, settings.aliases)
    state = _state(last_week=last_week)
    result = optimize(
        current_week=week,
        games=games,
        snapshots=snapshots,
        now=now,
        settings=settings,
        state=state,
        aliases=settings.aliases,
    )
    future = [p for p in result["projected_path"] if p.week not in {1, 15}]
    assert future
    assert all(p.source == "ratings" for p in future)
    week15 = next(p for p in result["projected_path"] if p.week == 15)
    assert week15.source == "market"
