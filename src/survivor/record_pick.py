from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from src.settings import canonicalize, load_settings
from src.survivor.state import ConflictError, apply_commit, load_state, save_state


def _load_dashboard(url: str) -> dict[str, Any]:
    resp = httpx.get(url, timeout=20.0, headers={"User-Agent": "nfl-survivor/0.1"})
    resp.raise_for_status()
    return resp.json()


def record_pick(
    *,
    team: str,
    week: str | int | None,
    loss: bool,
    replace: bool,
    config_dir: Path | None = None,
    state_path: Path | None = None,
    dashboard_json: dict[str, Any] | None = None,
    dashboard_url: str | None = None,
) -> tuple[int, str]:
    settings = load_settings(config_dir=config_dir)
    path = state_path or settings.state_path
    state = load_state(path)

    need_dash = (not str(team or "").strip()) or (week in (None, "", 0, "0"))
    payload = dashboard_json
    if need_dash and payload is None:
        url = dashboard_url if dashboard_url is not None else settings.dashboard_url
        rec_url = url.rstrip("/") + "/recommendations.json" if url else ""
        if not rec_url:
            return 1, "dashboard_url missing; cannot resolve empty team/week"
        try:
            payload = _load_dashboard(rec_url)
        except Exception as exc:
            return 1, f"failed to GET recommendations.json: {exc}"

    resolved_week: int | None
    if week in (None, "", 0, "0"):
        if not payload or payload.get("week") is None:
            return 1, "week missing and dashboard JSON has no week"
        resolved_week = int(payload["week"])
    else:
        resolved_week = int(week)

    team_raw = (team or "").strip()
    overwrite = True
    if not team_raw:
        existing = state.committed.get(resolved_week)
        if existing:
            resolved_team = existing
            overwrite = False
        else:
            primary = (payload or {}).get("primary") or {}
            resolved_team = primary.get("team")
            if not resolved_team:
                return 1, "empty team and dashboard primary missing"
    else:
        resolved_team = canonicalize(team_raw, settings.aliases)
        if resolved_team is None:
            return 1, f"unmapped team: {team_raw}"

    before = json.dumps(state.__dict__, sort_keys=True, default=str)
    try:
        apply_commit(
            state,
            resolved_team,
            resolved_week,
            loss=loss,
            replace=replace,
            overwrite=overwrite,
        )
    except ConflictError as exc:
        return 1, str(exc)
    after = json.dumps(state.__dict__, sort_keys=True, default=str)
    if before == after:
        return 0, "no-op"
    save_state(path, state)
    msg = f"ops: lock week {resolved_week} {state.committed.get(resolved_week)}"
    if loss:
        msg += " · loss"
    return 0, msg


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="src.survivor.record_pick")
    p.add_argument("--team", default=os.environ.get("INPUT_TEAM", ""))
    p.add_argument("--week", default=os.environ.get("INPUT_WEEK", ""))
    p.add_argument("--loss", action="store_true")
    p.add_argument("--replace", action="store_true")
    p.add_argument("--state", default="")
    p.add_argument("--config-dir", default="")
    p.add_argument("--dashboard-json", default="")
    args = p.parse_args(argv)
    loss = args.loss or str(os.environ.get("INPUT_LOSS", "")).lower() in {"1", "true", "yes"}
    replace = args.replace or str(os.environ.get("INPUT_REPLACE", "")).lower() in {"1", "true", "yes"}
    dash = None
    if args.dashboard_json:
        dash = json.loads(Path(args.dashboard_json).read_text(encoding="utf-8"))
    code, msg = record_pick(
        team=args.team,
        week=args.week,
        loss=loss,
        replace=replace,
        config_dir=Path(args.config_dir) if args.config_dir else None,
        state_path=Path(args.state) if args.state else None,
        dashboard_json=dash,
    )
    print(msg)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
