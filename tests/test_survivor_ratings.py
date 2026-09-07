from datetime import datetime, timezone

from src.settings import load_settings
from src.survivor.optimize import optimize, score_side
from src.survivor.probability import no_vig_pair, probability_to_american
from src.survivor.ratings import fit_ratings, logit, predict_p, sigmoid, spread_to_p
from src.survivor.types import Game, PoolState, Snapshot

NOW = datetime(2026, 9, 8, 16, tzinfo=timezone.utc)


def _aliases():
    return load_settings().aliases


def _snap(home: str, away: str, p_home: float, *, ts=NOW, game_id: str | None = None) -> Snapshot:
    home_ml = probability_to_american(p_home)
    away_ml = probability_to_american(1.0 - p_home)
    return Snapshot(
        snapshot_ts=ts,
        home=home,
        away=away,
        game_id=game_id or f"{home}-{away}",
        h2h={home: home_ml, away: away_ml},
    )


def test_spread_to_p_home_favorite():
    assert spread_to_p(-7.0) > 0.7
    assert spread_to_p(7.0) < 0.3
    assert abs(spread_to_p(0.0) - 0.5) < 1e-9


def test_fit_recovers_two_known_ratings():
    aliases = _aliases()
    hfa = 0.58
    r_a, r_b = 1.2, -1.2
    p_ab = sigmoid(r_a - r_b + logit(hfa))
    p_ba = sigmoid(r_b - r_a + logit(hfa))
    snaps = [
        _snap("Buffalo Bills", "Miami Dolphins", p_ab, game_id="g1"),
        _snap("Miami Dolphins", "Buffalo Bills", p_ba, game_id="g2"),
    ]
    fitted = fit_ratings(snaps, aliases, hfa=hfa, ridge=0.01)
    assert fitted is not None
    assert fitted["Buffalo Bills"] > fitted["Miami Dolphins"]
    assert abs(fitted["Buffalo Bills"] + fitted["Miami Dolphins"]) < 0.05
    pred = predict_p("Buffalo Bills", "Miami Dolphins", is_home=True, ratings=fitted, hfa=hfa)
    assert abs(pred - p_ab) < 0.03


def test_unobserved_matchup_predicts_home_prior():
    aliases = _aliases()
    hfa = 0.58
    snaps = [_snap("Buffalo Bills", "Miami Dolphins", 0.75)]
    fitted = fit_ratings(snaps, aliases, hfa=hfa, ridge=2.0)
    assert fitted is not None
    p = predict_p(
        "Chicago Bears",
        "Detroit Lions",
        is_home=True,
        ratings=fitted,
        hfa=hfa,
    )
    assert abs(p - hfa) < 1e-9


def test_spread_only_snapshot_in_fit_and_score():
    aliases = _aliases()
    settings = load_settings()
    snap = Snapshot(
        snapshot_ts=NOW,
        home="Buffalo Bills",
        away="Miami Dolphins",
        game_id="spread-only",
        h2h={},
        spreads={"Buffalo Bills": -7.0, "Miami Dolphins": 7.0},
    )
    fitted = fit_ratings([snap], aliases, hfa=0.58, ridge=0.05)
    assert fitted is not None
    assert fitted["Buffalo Bills"] > fitted["Miami Dolphins"]
    game = Game(
        game_id="spread-only",
        week=3,
        home="Buffalo Bills",
        away="Miami Dolphins",
        kickoff=datetime(2026, 9, 27, 17, tzinfo=timezone.utc),
        home_canonical="Buffalo Bills",
        away_canonical="Miami Dolphins",
    )
    side = score_side(
        game=game,
        team="Buffalo Bills",
        opponent="Miami Dolphins",
        is_home=True,
        snapshots=[snap],
        now=NOW,
        settings=settings,
        aliases=aliases,
        this_week=False,
        ratings=fitted,
    )
    assert side is not None
    assert side.source == "market"
    assert "SPREAD_NO_H2H" in side.flags
    assert abs(side.p_final - spread_to_p(-7.0)) < 1e-9


def test_ratings_disabled_keeps_flat_prior():
    from dataclasses import replace

    settings = replace(load_settings(), ratings=replace(load_settings().ratings, enabled=False))
    game = Game(
        game_id="later",
        week=4,
        home="Detroit Lions",
        away="New York Giants",
        kickoff=datetime(2026, 10, 4, 17, tzinfo=timezone.utc),
        home_canonical="Detroit Lions",
        away_canonical="New York Giants",
    )
    side = score_side(
        game=game,
        team="Detroit Lions",
        opponent="New York Giants",
        is_home=True,
        snapshots=[],
        now=NOW,
        settings=settings,
        aliases=settings.aliases,
        this_week=False,
        ratings={"Detroit Lions": 2.0, "New York Giants": -2.0},
    )
    assert side is not None
    assert side.source == "prior"
    assert "PRIOR_NO_MARKET" in side.flags
    assert side.p_final == settings.home_prior


def test_score_side_future_uses_ratings_not_flat_prior():
    settings = load_settings()
    aliases = settings.aliases
    ratings = {"Detroit Lions": 1.5, "New York Giants": -1.5}
    game = Game(
        game_id="later",
        week=4,
        home="Detroit Lions",
        away="New York Giants",
        kickoff=datetime(2026, 10, 4, 17, tzinfo=timezone.utc),
        home_canonical="Detroit Lions",
        away_canonical="New York Giants",
    )
    side = score_side(
        game=game,
        team="Detroit Lions",
        opponent="New York Giants",
        is_home=True,
        snapshots=[],
        now=NOW,
        settings=settings,
        aliases=aliases,
        this_week=False,
        ratings=ratings,
    )
    assert side is not None
    assert side.source == "ratings"
    assert "RATINGS_PRIOR" in side.flags
    assert "PRIOR_NO_MARKET" not in side.flags
    assert side.p_final > settings.home_prior
    assert side.line_source == "ratings"


def test_save_later_hammer_not_max_this_week_ml():
    settings = load_settings()
    aliases = settings.aliases
    kick1 = datetime(2026, 9, 13, 17, tzinfo=timezone.utc)
    kick2 = datetime(2026, 9, 20, 17, tzinfo=timezone.utc)
    games = [
        Game(
            game_id="w1-a",
            week=1,
            home="New York Giants",
            away="Detroit Lions",
            kickoff=kick1,
            home_canonical="New York Giants",
            away_canonical="Detroit Lions",
        ),
        Game(
            game_id="w1-b",
            week=1,
            home="Houston Texans",
            away="Jacksonville Jaguars",
            kickoff=kick1,
            home_canonical="Houston Texans",
            away_canonical="Jacksonville Jaguars",
        ),
        Game(
            game_id="w2-a",
            week=2,
            home="Detroit Lions",
            away="Arizona Cardinals",
            kickoff=kick2,
            home_canonical="Detroit Lions",
            away_canonical="Arizona Cardinals",
        ),
        Game(
            game_id="w2-fill",
            week=2,
            home="Chicago Bears",
            away="Carolina Panthers",
            kickoff=kick2,
            home_canonical="Chicago Bears",
            away_canonical="Carolina Panthers",
        ),
    ]
    snapshots = [
        Snapshot(
            snapshot_ts=NOW,
            home="New York Giants",
            away="Detroit Lions",
            game_id="w1-a",
            h2h={"Detroit Lions": -900, "New York Giants": 900},
        ),
        Snapshot(
            snapshot_ts=NOW,
            home="Houston Texans",
            away="Jacksonville Jaguars",
            game_id="w1-b",
            h2h={"Jacksonville Jaguars": -355, "Houston Texans": 355},
        ),
        Snapshot(
            snapshot_ts=NOW,
            home="Dallas Cowboys",
            away="Arizona Cardinals",
            game_id="look-ahead-weak",
            h2h={"Dallas Cowboys": -900, "Arizona Cardinals": 900},
        ),
    ]
    state = PoolState(
        season=2026,
        lives_remaining=1,
        used_teams=[],
        committed={},
        notes="",
        pool_name="NFL Survivor",
        tie_rule="loss",
        last_week=2,
    )
    result = optimize(
        current_week=1,
        games=games,
        snapshots=snapshots,
        now=NOW,
        settings=settings,
        state=state,
        aliases=aliases,
    )
    greedy = result["greedy_this_week"]
    primary = result["primary"]
    assert greedy is not None and primary is not None
    lions_p, _ = no_vig_pair(-900, 900)
    jags_p, _ = no_vig_pair(-355, 355)
    assert lions_p > jags_p
    assert greedy.team == "Detroit Lions"
    assert primary.team != greedy.team
    assert primary.team == "Jacksonville Jaguars"
    later = next(step for step in result["projected_path"] if step.week == 2)
    assert later.team == "Detroit Lions"
    assert later.source == "ratings"
    assert later.p_win > settings.home_prior
