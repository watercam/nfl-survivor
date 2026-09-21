from src.sleeper.price import (
    Leg,
    inv_phi,
    more_threshold,
    parse_pick_csv,
    phi,
    poisson_cdf,
    poisson_lambda_for_over,
    price_leg,
    price_slip,
)
from src.survivor.probability import no_vig_pair


def test_more_threshold_integer_and_half():
    assert more_threshold(40) == 40
    assert more_threshold(40.0) == 40
    assert more_threshold(39.5) == 40
    assert more_threshold(4) == 4
    assert more_threshold(4.5) == 5


def test_phi_inv_roundtrip():
    for z in (-1.5, 0.0, 0.8):
        assert abs(inv_phi(phi(z)) - z) < 1e-6


def test_even_juice_main_is_median_normal():
    row = price_leg(
        Leg(stat="rush_yds", alt=52.5, side="more", multiplier=1.8, main=52.5, sigma=32.0)
    )
    assert abs(row.p_fair - 0.5) < 0.01
    assert abs(row.mu - 52.5) < 0.2
    assert "SIGMA_HEURISTIC" in row.flags


def test_easier_rush_alt_is_favorite():
    """Screenshot-style 40+ vs a ~52.5 RB line: MORE is well above 50%."""
    row = price_leg(
        Leg(
            player="Cam Skattebo",
            stat="rush_yds",
            alt=40,
            side="more",
            multiplier=1.34,
            main=52.5,
            over_odds=-110,
            under_odds=-110,
        )
    )
    assert row.p_fair > 0.62
    assert row.p_sleeper == 1.0 / 1.34
    # 1.34x on a ~66% shot is short of fair (~1.52x) → negative EV
    assert row.fair_multiplier > 1.34
    assert row.ev < 0


def test_pass_yards_screenshot_shape():
    row = price_leg(
        Leg(
            player="Matthew Stafford",
            stat="pass_yds",
            alt=200,
            side="more",
            multiplier=1.26,
            main=245.5,
        )
    )
    assert 0.70 < row.p_fair < 0.85
    assert abs(row.p_sleeper - 1 / 1.26) < 1e-9


def test_poisson_receptions_four_plus():
    # Over 5.5 rec at even juice → λ near 5.5; 4+ is a goblin-style favorite.
    row = price_leg(
        Leg(stat="receptions", alt=4, side="more", multiplier=1.36, main=5.5)
    )
    assert row.model == "poisson"
    assert row.p_fair > 0.75
    assert row.ev > 0


def test_less_is_complement_of_more():
    more = price_leg(Leg(stat="rush_yds", alt=40, side="more", multiplier=1.5, main=52.5))
    less = price_leg(Leg(stat="rush_yds", alt=40, side="less", multiplier=1.5, main=52.5))
    assert abs(more.p_fair + less.p_fair - 1.0) < 1e-9


def test_book_odds_skips_distribution():
    row = price_leg(
        Leg(stat="rush_yds", alt=40, side="more", multiplier=1.34, book_odds=-250)
    )
    # -250 implied ≈ 71.4% (vig in)
    assert abs(row.p_fair - 250 / 350) < 1e-9
    assert row.source == "book_implied"
    assert "BOOK_VIG_IN" in row.flags


def test_book_two_way_devig():
    row = price_leg(
        Leg(
            stat="rush_yds",
            alt=40,
            side="more",
            multiplier=1.34,
            book_odds=-200,
            book_opp_odds=170,
        )
    )
    fair, _ = no_vig_pair(-200, 170)
    assert abs(row.p_fair - fair) < 1e-12
    assert row.source == "book_devig"


def test_anytime_td_yes():
    row = price_leg(
        Leg(stat="anytime_td", alt=1, side="more", multiplier=1.5, book_odds=-140)
    )
    assert abs(row.p_fair - 140 / 240) < 1e-9


def test_slip_product_and_independence():
    slip = price_slip(
        [
            Leg(stat="rush_yds", alt=40, side="more", multiplier=1.34, main=52.5),
            Leg(stat="pass_yds", alt=200, side="more", multiplier=1.26, main=245.5),
        ]
    )
    assert abs(slip.payout - 1.34 * 1.26) < 1e-9
    assert abs(slip.p_all - slip.legs[0].p_fair * slip.legs[1].p_fair) < 1e-12
    assert abs(slip.ev - (slip.p_all * slip.payout - 1.0)) < 1e-12


def test_parse_pick_csv_and_book_suffix():
    a = parse_pick_csv("rush_yds,40,more,1.34,52.5,-110,-110")
    assert a.stat == "rush_yds"
    assert a.alt == 40
    assert a.main == 52.5
    b = parse_pick_csv("rush_yds,40,more,1.34@-250")
    assert b.book_odds == -250
    assert b.main is None


def test_poisson_lambda_even_over_half():
    lam = poisson_lambda_for_over(4.5, 0.5)
    # P(X >= 5) = 0.5 ⇒ P(X <= 4) = 0.5
    assert abs(poisson_cdf(4, lam) - 0.5) < 1e-6
