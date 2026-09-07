from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx

from src.settings import Settings, abbr_for


def _fmt_p(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def format_success(
    payload: dict[str, Any],
    *,
    settings: Settings,
    aliases: list[dict[str, str]] | None = None,
) -> str:
    aliases = aliases or []
    week = payload.get("week")
    lives = payload.get("lives_remaining")
    used = len(payload.get("used_teams") or [])
    lines = [
        f"NFL Survivor week {week} · lives {lives} · used {used}",
        f"generated_at: {payload.get('generated_at')}",
    ]
    dash = settings.dashboard_url or "(set slate.dashboard_url)"
    lines.append(f"dashboard: {dash}")
    primary = payload.get("primary") or {}
    status = payload.get("status")
    if status == "eliminated" or not primary:
        lines.append("status: eliminated — no recommend")
    else:
        team = primary.get("team")
        opp = primary.get("opponent")
        kick = primary.get("kickoff")
        lines.append(
            f"pick: {team} over {opp} @ {kick}  p_final={_fmt_p(primary.get('p_final'))}  "
            f"survive_p={_fmt_p(primary.get('survive_p'))}"
        )
        greedy = payload.get("greedy_this_week") or {}
        if greedy.get("team") and greedy.get("team") != team:
            lines.append(
                f"why-not-greedy: saved {greedy.get('team')} for later "
                f"(this-week p_final={_fmt_p(greedy.get('p_final'))})"
            )
        locked = payload.get("committed_this_week")
        if locked:
            lines.append(f"locked pick: {locked}")
        summary = payload.get("executive_summary")
        if isinstance(summary, list):
            lines.extend(f"• {item}" for item in summary if item)
        elif summary:
            lines.append(str(summary))
    alts = (payload.get("alternatives") or [])[:3]
    if alts:
        bits = []
        for a in alts:
            ab = abbr_for(a.get("team") or "", aliases) if aliases else (a.get("team") or "")
            bits.append(f"{ab} survive={_fmt_p(a.get('survive_p'))}")
        lines.append("alts: " + " · ".join(bits))
    alerts = payload.get("alerts") or []
    if alerts:
        kinds = ", ".join(a.get("kind") for a in alerts if a.get("kind"))
        lines.append(f"alerts: {kinds}")

    record_url = payload.get("record_pick_url") or settings.record_pick_url()
    suggested = (primary or {}).get("team") or ""
    if record_url:
        lines.append("")
        lines.append(f"<{record_url}|Record pick>")
        lines.append(f"week {week} · suggested {suggested}")
        lines.append("empty Team = lock suggested")
    refresh = settings.refresh_workflow_url()
    if refresh:
        lines.append(f"<{refresh}|Refresh rankings>")
    return "\n".join(lines)


def format_failure(message: str) -> str:
    return message


def post_webhook(text: str, *, webhook_url: str | None = None) -> None:
    url = webhook_url if webhook_url is not None else os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return
    resp = httpx.post(url, json={"text": text}, timeout=20.0)
    resp.raise_for_status()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--failure", default="")
    args = parser.parse_args(argv)
    if args.failure:
        run_url = os.environ.get("GITHUB_RUN_URL") or os.environ.get("RUN_URL") or ""
        if "{RUN_URL}" in args.failure:
            msg = args.failure.replace("{RUN_URL}", run_url)
        else:
            msg = args.failure
        # Prefer refresh run URL on failure (not record-pick).
        if not run_url:
            repo = os.environ.get("GITHUB_REPOSITORY") or ""
            run_id = os.environ.get("GITHUB_RUN_ID") or ""
            if repo and run_id:
                run_url = f"https://github.com/{repo}/actions/runs/{run_id}"
                if "http" not in msg:
                    msg = f"{msg} {run_url}".strip()
        post_webhook(format_failure(msg))
        return 0
    print("use format_success() from the runner", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
