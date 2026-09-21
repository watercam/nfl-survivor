from __future__ import annotations

import argparse
import json
import sys

from src.sleeper.price import STATS, Leg, parse_pick_csv, price_slip
from src.survivor.probability import format_american


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="src.sleeper.run",
        description=(
            "Price Sleeper ALT multipliers against a sportsbook main line "
            "(or against the book's American price at the same alt)."
        ),
    )
    p.add_argument("--player", default="", help="optional label")
    p.add_argument("--stat", default="", help="rush_yds, pass_yds, receptions, …")
    p.add_argument("--alt", type=float, default=None, help="Sleeper line (40 for 40+)")
    p.add_argument("--side", default="more", help="more/less (over/under aliases ok)")
    p.add_argument("--mult", "--multiplier", dest="mult", type=float, default=None)
    p.add_argument("--main", type=float, default=None, help="sportsbook O/U (e.g. 52.5)")
    p.add_argument("--over", type=int, default=-110, help="sportsbook over American")
    p.add_argument("--under", type=int, default=-110, help="sportsbook under American")
    p.add_argument("--sigma", type=float, default=None, help="override residual SD")
    p.add_argument(
        "--book-odds",
        type=int,
        default=None,
        help="sportsbook American at THIS alt/side (skips the distribution)",
    )
    p.add_argument(
        "--book-opp",
        type=int,
        default=None,
        help="other side at the same alt; used to no-vig --book-odds",
    )
    p.add_argument(
        "--pick",
        action="append",
        default=[],
        help="stat,alt,side,mult[,main[,over[,under[,sigma]]]][@american] (repeat)",
    )
    p.add_argument("--json", action="store_true")
    p.add_argument("--list-stats", action="store_true")
    return p.parse_args(argv)


def _legs_from_args(args: argparse.Namespace) -> list[Leg]:
    legs: list[Leg] = []
    for raw in args.pick:
        legs.append(parse_pick_csv(raw))
    if args.stat or args.alt is not None or args.mult is not None:
        if not args.stat or args.alt is None or args.mult is None:
            raise ValueError("single-leg mode needs --stat --alt --mult")
        legs.append(
            Leg(
                player=args.player,
                stat=args.stat,
                alt=args.alt,
                side=args.side,
                multiplier=args.mult,
                main=args.main,
                over_odds=args.over,
                under_odds=args.under,
                sigma=args.sigma,
                book_odds=args.book_odds,
                book_opp_odds=args.book_opp,
            )
        )
    if not legs:
        raise ValueError("provide --stat/--alt/--mult or one or more --pick")
    if args.player and len(legs) == 1 and not legs[0].player:
        legs[0].player = args.player
    return legs


def _fmt_pct(p: float) -> str:
    return f"{100.0 * p:.1f}%"


def _fmt_edge(ev: float) -> str:
    sign = "+" if ev >= 0 else ""
    return f"{sign}{100.0 * ev:.1f}%"


def print_slip(slip) -> None:
    print(
        f"{'player':<16} {'stat':<14} {'alt':>6} {'side':<5} {'sleeper':>8} "
        f"{'fair':>8} {'p_mkt':>7} {'p_slp':>7} {'edge':>8}  source"
    )
    for row in slip.legs:
        who = (row.player or "—")[:16]
        alt = f"{row.alt:g}+"
        print(
            f"{who:<16} {row.stat:<14} {alt:>6} {row.side:<5} "
            f"{row.multiplier:>7.2f}x {row.fair_multiplier:>7.2f}x "
            f"{_fmt_pct(row.p_fair):>7} {_fmt_pct(row.p_sleeper):>7} "
            f"{_fmt_edge(row.ev):>8}  {row.source}"
        )
        extra = []
        if row.mu is not None:
            extra.append(f"μ={row.mu:.1f}")
        if row.sigma is not None and row.model == "normal":
            extra.append(f"σ={row.sigma:.1f}")
        extra.append(f"fair {format_american(row.fair_american)}")
        if row.flags:
            extra.append(",".join(row.flags))
        print("  " + " · ".join(extra))
    if len(slip.legs) > 1:
        print()
        print(
            f"slip  payout {slip.payout:.2f}x  p(all hit) {_fmt_pct(slip.p_all)}  "
            f"fair {slip.fair_payout:.2f}x  EV {_fmt_edge(slip.ev)}"
        )
        print("  independence assumed; same-game correlation is not priced")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.list_stats:
        for key, meta in STATS.items():
            print(f"{key:<14} {meta['model']:<10} sigma={meta['sigma']}  {meta['label']}")
        return 0
    try:
        legs = _legs_from_args(args)
        slip = price_slip(legs)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(slip.as_dict(), indent=2))
        return 0
    print_slip(slip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
