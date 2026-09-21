from __future__ import annotations

import math
from dataclasses import dataclass, field

from src.survivor.probability import american_to_implied, no_vig_pair, probability_to_american

# Residual SDs are NFL player-game heuristics. Override with --sigma when you
# have a better number. Counting stats use Poisson so the mean is the line.
STATS: dict[str, dict[str, object]] = {
    "rush_yds": {"model": "normal", "sigma": 32.0, "label": "rushing yards"},
    "qb_rush_yds": {"model": "normal", "sigma": 18.0, "label": "QB rushing yards"},
    "pass_yds": {"model": "normal", "sigma": 62.0, "label": "passing yards"},
    "rec_yds": {"model": "normal", "sigma": 27.0, "label": "receiving yards"},
    "rush_rec_yds": {"model": "normal", "sigma": 35.0, "label": "rush + rec yards"},
    "receptions": {"model": "poisson", "sigma": 2.1, "label": "receptions"},
    "rush_att": {"model": "poisson", "sigma": 4.5, "label": "rush attempts"},
    "pass_att": {"model": "normal", "sigma": 6.5, "label": "pass attempts"},
    "completions": {"model": "normal", "sigma": 5.0, "label": "completions"},
    "pass_tds": {"model": "poisson", "sigma": 0.85, "label": "passing TDs"},
    "rush_tds": {"model": "poisson", "sigma": 0.55, "label": "rushing TDs"},
    "rec_tds": {"model": "poisson", "sigma": 0.45, "label": "receiving TDs"},
    "rush_rec_td": {"model": "poisson", "sigma": 0.7, "label": "rush + rec TDs"},
    "fantasy": {"model": "normal", "sigma": 7.5, "label": "fantasy points"},
    "anytime_td": {"model": "bernoulli", "sigma": None, "label": "anytime TD"},
}

SIDES = ("more", "less")


def phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def inv_phi(p: float) -> float:
    p = min(max(p, 1e-12), 1.0 - 1e-12)
    lo, hi = -8.0, 8.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if phi(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def poisson_pmf_series(k_max: int, lam: float) -> list[float]:
    """P(X=0) … P(X=k_max) via recurrence (stable for moderate λ)."""
    if lam < 0:
        raise ValueError("lambda must be >= 0")
    if k_max < 0:
        return []
    out = [math.exp(-lam)]
    for i in range(1, k_max + 1):
        out.append(out[-1] * lam / i)
    return out


def poisson_cdf(k: int, lam: float) -> float:
    if k < 0:
        return 0.0
    return min(1.0, sum(poisson_pmf_series(k, lam)))


def poisson_lambda_for_over(line: float, p_over: float) -> float:
    """λ such that P(X > line) ≈ p_over. For 4.5 that is P(X >= 5)."""
    p_over = min(max(p_over, 1e-6), 1.0 - 1e-6)
    k = int(math.floor(line))
    target_cdf = 1.0 - p_over
    lo, hi = 1e-8, 400.0
    for _ in range(90):
        mid = (lo + hi) / 2.0
        cdf = poisson_cdf(k, mid)
        if cdf > target_cdf:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def more_threshold(alt: float) -> int:
    """Smallest integer that counts as MORE on a Sleeper-style N+ / Over line."""
    if alt <= 0:
        raise ValueError("alt line must be positive")
    if abs(alt - round(alt)) < 1e-9:
        return int(round(alt))
    return int(math.floor(alt)) + 1


def p_more_normal(mu: float, sigma: float, alt: float) -> float:
    if sigma <= 0:
        raise ValueError("sigma must be positive")
    t = more_threshold(alt)
    # continuity: P(X >= t) ≈ 1 - Φ((t - 0.5 - μ) / σ)
    return 1.0 - phi((t - 0.5 - mu) / sigma)


def p_more_poisson(lam: float, alt: float) -> float:
    if lam < 0:
        raise ValueError("lambda must be >= 0")
    t = more_threshold(alt)
    return 1.0 - poisson_cdf(t - 1, lam)


def p_over_main_normal(mu: float, sigma: float, main: float) -> float:
    return 1.0 - phi((main - mu) / sigma)


def no_vig_over(over_odds: int | float, under_odds: int | float) -> float:
    p_over, _p_under = no_vig_pair(over_odds, under_odds)
    return p_over


def mean_from_main(
    *,
    model: str,
    main: float,
    p_over: float,
    sigma: float | None,
) -> float:
    if model == "poisson":
        return poisson_lambda_for_over(main, p_over)
    if model == "normal":
        if sigma is None or sigma <= 0:
            raise ValueError("normal model needs a positive sigma")
        # P(X > main) = p_over → μ = main − σ Φ^{-1}(1 − p_over)
        return main - sigma * inv_phi(1.0 - p_over)
    raise ValueError(f"cannot back out a mean for model {model}")


@dataclass
class Leg:
    stat: str
    alt: float
    side: str
    multiplier: float
    main: float | None = None
    over_odds: int | float | None = -110
    under_odds: int | float | None = -110
    sigma: float | None = None
    book_odds: int | float | None = None
    book_opp_odds: int | float | None = None
    player: str = ""


@dataclass
class LegPrice:
    player: str
    stat: str
    label: str
    alt: float
    side: str
    multiplier: float
    p_sleeper: float
    p_fair: float
    fair_multiplier: float
    edge: float
    ev: float
    fair_american: int
    model: str
    mu: float | None
    sigma: float | None
    p_over_main: float | None
    source: str
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "player": self.player,
            "stat": self.stat,
            "label": self.label,
            "alt": self.alt,
            "side": self.side,
            "multiplier": round(self.multiplier, 4),
            "p_sleeper": round(self.p_sleeper, 6),
            "p_fair": round(self.p_fair, 6),
            "fair_multiplier": round(self.fair_multiplier, 4),
            "edge": round(self.edge, 6),
            "ev": round(self.ev, 6),
            "fair_american": self.fair_american,
            "model": self.model,
            "mu": None if self.mu is None else round(self.mu, 4),
            "sigma": None if self.sigma is None else round(self.sigma, 4),
            "p_over_main": None if self.p_over_main is None else round(self.p_over_main, 6),
            "source": self.source,
            "flags": list(self.flags),
        }


def resolve_stat(stat: str) -> dict[str, object]:
    key = stat.strip().lower().replace(" ", "_").replace("+", "_")
    aliases = {
        "rushing_yards": "rush_yds",
        "passing_yards": "pass_yds",
        "receiving_yards": "rec_yds",
        "rec": "receptions",
        "reception": "receptions",
        "pass_yards": "pass_yds",
        "rush_yards": "rush_yds",
        "rec_yards": "rec_yds",
        "att": "rush_att",
        "anytime": "anytime_td",
        "td": "anytime_td",
    }
    key = aliases.get(key, key)
    if key not in STATS:
        known = ", ".join(sorted(STATS))
        raise ValueError(f"unknown stat {stat!r}; try one of: {known}")
    return {"key": key, **STATS[key]}


def _p_fair_from_book(leg: Leg) -> tuple[float, str, list[str]]:
    flags: list[str] = []
    if leg.book_opp_odds is not None:
        p_this, _p_opp = no_vig_pair(leg.book_odds, leg.book_opp_odds)  # type: ignore[arg-type]
        flags.append("BOOK_TWO_WAY")
        return p_this, "book_devig", flags
    p = american_to_implied(leg.book_odds)  # type: ignore[arg-type]
    flags.append("BOOK_VIG_IN")
    return p, "book_implied", flags


def price_leg(leg: Leg) -> LegPrice:
    side = leg.side.strip().lower()
    if side in {"over", "o", "yes"}:
        side = "more"
    if side in {"under", "u", "no"}:
        side = "less"
    if side not in SIDES:
        raise ValueError("side must be more or less")
    if leg.multiplier <= 1.0:
        raise ValueError("Sleeper multiplier must be > 1")

    meta = resolve_stat(leg.stat)
    key = str(meta["key"])
    model = str(meta["model"])
    label = str(meta["label"])
    sigma = leg.sigma if leg.sigma is not None else meta["sigma"]
    sigma_f = None if sigma is None else float(sigma)
    flags: list[str] = []
    mu: float | None = None
    p_over_main: float | None = None
    source: str

    p_sleeper = 1.0 / float(leg.multiplier)

    if key == "anytime_td" or model == "bernoulli":
        if leg.book_odds is None:
            raise ValueError("anytime TD needs --book-odds (sportsbook Yes price)")
        p_yes, source, bflags = _p_fair_from_book(leg)
        flags.extend(bflags)
        p_fair = p_yes if side == "more" else 1.0 - p_yes
    elif leg.book_odds is not None:
        p_book, source, bflags = _p_fair_from_book(leg)
        flags.extend(bflags)
        p_fair = p_book
        flags.append("ALT_MATCHED_TO_BOOK")
    else:
        if leg.main is None:
            raise ValueError("need a sportsbook main line (--main) or --book-odds at this alt")
        over_odds = -110 if leg.over_odds is None else leg.over_odds
        under_odds = -110 if leg.under_odds is None else leg.under_odds
        p_over_main = no_vig_over(over_odds, under_odds)
        mu = mean_from_main(model=model, main=float(leg.main), p_over=p_over_main, sigma=sigma_f)
        if model == "poisson":
            p_m = p_more_poisson(mu, float(leg.alt))
            source = "poisson_from_main"
        else:
            p_m = p_more_normal(mu, float(sigma_f), float(leg.alt))
            source = "normal_from_main"
            flags.append("SIGMA_HEURISTIC")
        p_fair = p_m if side == "more" else 1.0 - p_m

    p_fair = min(max(p_fair, 1e-6), 1.0 - 1e-6)
    fair_mult = 1.0 / p_fair
    ev = p_fair * float(leg.multiplier) - 1.0
    return LegPrice(
        player=leg.player,
        stat=key,
        label=label,
        alt=float(leg.alt),
        side=side,
        multiplier=float(leg.multiplier),
        p_sleeper=p_sleeper,
        p_fair=p_fair,
        fair_multiplier=fair_mult,
        edge=ev,
        ev=ev,
        fair_american=probability_to_american(p_fair),
        model=model,
        mu=mu,
        sigma=sigma_f,
        p_over_main=p_over_main,
        source=source,
        flags=flags,
    )


@dataclass
class SlipPrice:
    legs: list[LegPrice]
    payout: float
    p_all: float
    ev: float
    fair_payout: float

    def as_dict(self) -> dict[str, object]:
        return {
            "legs": [leg.as_dict() for leg in self.legs],
            "payout": round(self.payout, 4),
            "p_all": round(self.p_all, 6),
            "ev": round(self.ev, 6),
            "fair_payout": round(self.fair_payout, 4),
        }


def price_slip(legs: list[Leg]) -> SlipPrice:
    priced = [price_leg(leg) for leg in legs]
    payout = 1.0
    p_all = 1.0
    for row in priced:
        payout *= row.multiplier
        p_all *= row.p_fair
    return SlipPrice(
        legs=priced,
        payout=payout,
        p_all=p_all,
        ev=p_all * payout - 1.0,
        fair_payout=1.0 / p_all if p_all > 0 else float("inf"),
    )


def parse_pick_csv(raw: str) -> Leg:
    """stat,alt,side,mult[,main[,over[,under[,sigma]]]]  — or book odds via @-250."""
    text = raw.strip()
    book_odds: int | float | None = None
    if "@" in text:
        text, book = text.rsplit("@", 1)
        book_odds = int(book.strip())
        text = text.rstrip(",").strip()
    parts = [p.strip() for p in text.split(",")]
    if len(parts) < 4:
        raise ValueError(
            "pick format: stat,alt,side,mult[,main[,over[,under[,sigma]]]][@american]"
        )
    stat, alt_s, side, mult_s, *rest = parts
    main = float(rest[0]) if len(rest) >= 1 and rest[0] != "" else None
    over_odds: int | float | None = int(rest[1]) if len(rest) >= 2 and rest[1] != "" else -110
    under_odds: int | float | None = int(rest[2]) if len(rest) >= 3 and rest[2] != "" else -110
    sigma = float(rest[3]) if len(rest) >= 4 and rest[3] != "" else None
    return Leg(
        stat=stat,
        alt=float(alt_s),
        side=side,
        multiplier=float(mult_s),
        main=main,
        over_odds=over_odds,
        under_odds=under_odds,
        sigma=sigma,
        book_odds=book_odds,
    )
