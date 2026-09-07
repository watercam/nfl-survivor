from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.settings import REPO_ROOT, canonicalize, load_dotenv, load_settings
from src.survivor.odds import OddsClient
from src.survivor.optimize import optimize
from src.survivor.payload import build_payload, fetch_previous, load_fixture, print_table
from src.survivor.slate import fetch_espn_scoreboard, fetch_remaining_season, parse_espn_scoreboard
from src.survivor.slack import format_success, post_webhook
from src.survivor.state import apply_commit, apply_loss, load_state, save_state


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="src.survivor.run")
    p.add_argument("--fixture", type=str, default="")
    p.add_argument("--web", action="store_true")
    p.add_argument("--no-slack", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--commit", type=str, default="")
    p.add_argument("--loss", action="store_true")
    p.add_argument("--week", type=int, default=0)
    p.add_argument("--replace", action="store_true")
    p.add_argument("--state", type=str, default="")
    p.add_argument("--config-dir", type=str, default="")
    return p.parse_args(argv)


def _mutate_and_exit(args: argparse.Namespace) -> int:
    settings = load_settings(config_dir=Path(args.config_dir) if args.config_dir else None)
    state_path = Path(args.state) if args.state else settings.state_path
    state = load_state(state_path)
    week = args.week
    if args.commit:
        team = canonicalize(args.commit, settings.aliases)
        if team is None:
            print(f"unmapped team: {args.commit}", file=sys.stderr)
            return 1
        if not week:
            print("--week is required with --commit", file=sys.stderr)
            return 1
        apply_commit(state, team, week, loss=args.loss, replace=args.replace)
        save_state(state_path, state)
        print(f"locked week {week} {team}" + (" · loss" if args.loss else ""))
        return 0
    if args.loss:
        if not week:
            print("--week is required with --loss", file=sys.stderr)
            return 1
        apply_loss(state)
        save_state(state_path, state)
        print(f"week {week} recorded as loss; lives_remaining={state.lives_remaining}")
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)
    if args.commit or args.loss:
        return _mutate_and_exit(args)

    settings = load_settings(config_dir=Path(args.config_dir) if args.config_dir else None)
    state_path = Path(args.state) if args.state else settings.state_path
    state = load_state(state_path)
    aliases = settings.aliases

    if args.fixture:
        now, week, fixture_last, games, snapshots = load_fixture(Path(args.fixture), aliases)
        state.last_week = min(state.last_week, fixture_last)
    else:
        if not settings.odds_api_key:
            print("ODDS_API_KEY is required for live mode", file=sys.stderr)
            return 1
        now = datetime.now(timezone.utc)
        try:
            payload = fetch_espn_scoreboard(settings.espn_scoreboard_url)
            week, current_games, _ = parse_espn_scoreboard(payload, aliases=aliases)
            if not week:
                payload = fetch_espn_scoreboard(settings.espn_scoreboard_url, week=1)
                week, current_games, _ = parse_espn_scoreboard(
                    payload, aliases=aliases, week_fallback=1
                )
                week = week or 1
            if not week:
                print("ESPN payload missing week", file=sys.stderr)
                return 1
            week, games = fetch_remaining_season(
                settings.espn_scoreboard_url,
                current_week=week,
                last_week=min(state.last_week, settings.last_week),
                aliases=aliases,
            )
        except Exception as exc:
            print(f"ESPN slate failed: {exc}", file=sys.stderr)
            return 1
        odds = OddsClient(settings)
        try:
            this_kickoffs = [g.kickoff for g in games if g.week == week]
            snapshots = odds.snapshots_for_slate(
                this_week_kickoffs=this_kickoffs,
                now=now,
                reference_hours=settings.reference_hours,
            )
        except Exception as exc:
            print(f"Odds fetch failed: {exc}", file=sys.stderr)
            return 1
        finally:
            odds.close()

    result = optimize(
        current_week=week,
        games=games,
        snapshots=snapshots,
        now=now,
        settings=settings,
        state=state,
        aliases=aliases,
    )

    previous = None
    if not args.fixture:
        previous = fetch_previous(settings.dashboard_url)
    payload = build_payload(
        week=week,
        now=now,
        settings=settings,
        state=state,
        result=result,
        previous=previous,
        aliases=aliases,
    )

    print_table(
        week=week,
        state=state,
        status=result["status"],
        calibration=settings.calibration.source,
        ranked=result["all_ranked"],
        aliases=aliases,
    )
    print()
    print("alternatives:")
    for alt in result["alternatives"][1:]:
        print(f"  {alt.team} survive_p={alt.survive_p:.3f} p_final={alt.p_final:.2f}")
    print("projected path:")
    for step in result["projected_path"]:
        print(f"  w{step.week} {step.team or '(starve)'} p={step.p_win:.2f} {step.source}")

    if args.json:
        print(json.dumps(payload, indent=2))

    if args.web:
        out = REPO_ROOT / "web" / "recommendations.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")

    if not args.no_slack:
        skip = False
        if settings.slack_heartbeat == "changes_only" and previous:
            prev_cmp = {k: v for k, v in previous.items() if k != "generated_at"}
            cur_cmp = {k: v for k, v in payload.items() if k != "generated_at"}
            skip = prev_cmp == cur_cmp
        if not skip:
            text = format_success(payload, settings=settings, aliases=aliases)
            post_webhook(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
