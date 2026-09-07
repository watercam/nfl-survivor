"""Post NFL Survivor summaries to a Slack Incoming Webhook. Skip if unset."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Mapping, Optional

import requests

from src.settings import load_dotenv
from src.survivor.summary import format_pct

WEBHOOK_ENV = "SLACK_WEBHOOK_URL"
# Slack's table UI fades after ~8 body rows; 5 keeps a chunk fully visible.
TABLE_BODY_ROW_LIMIT = 5
SLACK_ALT_LIMIT = 3
# Dogs are legal optimizer rows; they are not useful "alternative picks" in Slack.
MIN_ALT_WIN = 0.5
_MRKDWN_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))
_HEADER_MAX = 150


def load_env() -> None:
    load_dotenv()


def post_survivor_update(
    payload: Mapping[str, Any],
    *,
    previous: Optional[Mapping[str, Any]] = None,
    dashboard_url: str = "",
    refresh_url: str = "",
    webhook_url: Optional[str] = None,
) -> bool:
    url = _webhook(webhook_url)
    if not url:
        return False
    _post_json(
        url,
        {
            "text": format_success_message(payload, previous=previous),
            "unfurl_links": False,
            "blocks": format_success_blocks(
                payload,
                previous=previous,
                dashboard_url=dashboard_url,
                refresh_url=refresh_url,
            ),
        },
    )
    return True


def post_failure(message: str, *, webhook_url: Optional[str] = None) -> bool:
    url = _webhook(webhook_url)
    if not url:
        return False
    _post_json(
        url,
        {
            "text": message,
            "unfurl_links": False,
            "blocks": format_failure_blocks(message),
        },
    )
    return True


def format_success_message(
    payload: Mapping[str, Any],
    *,
    previous: Optional[Mapping[str, Any]] = None,
    dashboard_url: str = "",
    refresh_url: str = "",
) -> str:
    del dashboard_url, refresh_url
    week = payload.get("week")
    week_label = "-" if week is None else str(week)
    lives = payload.get("lives_remaining")
    lives_label = "-" if lives is None else str(lives)
    used = len(payload.get("used_teams") or [])
    primary = payload.get("primary") or {}
    team = (primary.get("team") or "").strip()
    opp = (primary.get("opponent") or "").strip()
    if team and opp:
        matchup = f"{team} vs {opp}"
    elif team:
        matchup = team
    else:
        matchup = "no pick"
    summary = f"NFL Survivor week {week_label} · lives {lives_label} · used {used} · {matchup}"
    if _is_new_week(previous, payload):
        summary += " · new week slate"
    return summary


def format_success_blocks(
    payload: Mapping[str, Any],
    *,
    previous: Optional[Mapping[str, Any]] = None,
    dashboard_url: str = "",
    refresh_url: str = "",
) -> list[dict[str, Any]]:
    week = payload.get("week")
    week_label = "-" if week is None else str(week)
    header = f"NFL Survivor · Week {week_label}"
    if len(header) > _HEADER_MAX:
        header = header[: _HEADER_MAX - 1] + "…"
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": _context_text(payload, previous)}],
        },
        _primary_section(payload),
    ]
    if payload.get("status") != "eliminated":
        blocks.extend(_alternative_table_blocks(payload))
    alerts = _alert_lines(payload.get("alerts") or [])
    if alerts:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Alerts*\n" + "\n".join(alerts)},
            }
        )
    actions = _action_elements(dashboard_url, refresh_url)
    if actions:
        blocks.append({"type": "actions", "elements": actions})
    return blocks


def format_failure_blocks(message: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "NFL Survivor refresh failed"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": _escape_mrkdwn(message)},
        },
    ]


def _primary_section(payload: Mapping[str, Any]) -> dict[str, Any]:
    status = payload.get("status")
    primary = payload.get("primary") or {}
    team = (primary.get("team") or "").strip()
    if status == "eliminated" or not team:
        text = "There is no pick — the pool is eliminated."
        if status != "eliminated":
            text = "There is no pick this week."
        return {
            "type": "section",
            "expand": True,
            "text": {"type": "mrkdwn", "text": text},
        }
    opp = _escape_mrkdwn(str(primary.get("opponent") or ""))
    hero = f"*{_escape_mrkdwn(team)}* vs {opp}".rstrip()
    bits: list[str] = []
    kickoff = primary.get("kickoff")
    if kickoff:
        bits.append(str(kickoff))
    win = _fmt_pct(primary.get("p_final"))
    if win:
        bits.append(f"win {win}")
    survive = _fmt_pct(primary.get("survive_p"))
    if survive:
        bits.append(f"survive {survive}")
    source = primary.get("source")
    if source:
        bits.append(str(source))
    lines = [hero]
    if bits:
        lines.append(" · ".join(bits))
    greedy = payload.get("greedy_this_week") or {}
    greedy_team = (greedy.get("team") or "").strip()
    if greedy_team and greedy_team != team:
        greedy_win = _fmt_pct(greedy.get("p_final"))
        reason = f"Saved {_escape_mrkdwn(greedy_team)}"
        if greedy_win:
            reason += f" (this-week win {greedy_win})"
        reason += " for later."
        lines.append(f"_{reason}_")
    return {
        "type": "section",
        "expand": True,
        "text": {"type": "mrkdwn", "text": "\n".join(lines)},
    }


def _alternative_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    primary_team = ((payload.get("primary") or {}) or {}).get("team")
    rows: list[Mapping[str, Any]] = []
    for item in payload.get("alternatives") or []:
        if not isinstance(item, Mapping):
            continue
        if primary_team and item.get("team") == primary_team:
            continue
        p_final = item.get("p_final")
        if p_final is not None and p_final != "":
            try:
                if float(p_final) < MIN_ALT_WIN:
                    continue
            except (TypeError, ValueError):
                pass
        rows.append(item)
        if len(rows) >= SLACK_ALT_LIMIT:
            break
    return rows


def _alternative_table_blocks(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    ranked = _alternative_rows(payload)
    if not ranked:
        return []
    return [
        _alternatives_table(ranked[index : index + TABLE_BODY_ROW_LIMIT], start_rank=index + 1)
        for index in range(0, len(ranked), TABLE_BODY_ROW_LIMIT)
    ]


def _alternatives_table(ranked: list[Mapping[str, Any]], *, start_rank: int) -> dict[str, Any]:
    header = [
        _raw_text("Rank"),
        _raw_text("Team"),
        _raw_text("Opp"),
        _raw_text("Win"),
        _raw_text("Survive"),
        _raw_text("Source"),
    ]
    rows: list[list[dict[str, Any]]] = [header]
    for offset, alt in enumerate(ranked):
        rows.append(_alternative_row(alt, rank=start_rank + offset))
    return {
        "type": "table",
        "column_settings": [
            {"align": "right"},
            {"is_wrapped": True},
            {"is_wrapped": True},
            {"align": "right"},
            {"align": "right"},
            {"is_wrapped": True},
        ],
        "rows": rows,
    }


def _alternative_row(alt: Mapping[str, Any], *, rank: int) -> list[dict[str, Any]]:
    team = str(alt.get("team") or "")
    opp = alt.get("opponent")
    source = alt.get("source")
    return [
        _raw_text(str(rank)),
        _rich_text(team, bold=True),
        _raw_text("" if opp in (None, "") else str(opp)),
        _raw_text(_fmt_pct(alt.get("p_final")) or ""),
        _raw_text(_fmt_pct(alt.get("survive_p")) or ""),
        _raw_text("" if source in (None, "") else str(source)),
    ]


def _fmt_pct(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return format_pct(number)


def _context_text(payload: Mapping[str, Any], previous: Optional[Mapping[str, Any]]) -> str:
    lives = payload.get("lives_remaining")
    lives_label = "-" if lives is None else str(lives)
    used = len(payload.get("used_teams") or [])
    status = payload.get("status") or "-"
    bits = [
        f"lives `{_escape_mrkdwn(lives_label)}`",
        f"used `{used}`",
        f"status `{_escape_mrkdwn(str(status))}`",
        f"calibration `{_escape_mrkdwn(str(payload.get('calibration') or '-'))}`",
        f"generated_at `{_escape_mrkdwn(str(payload.get('generated_at') or '-'))}`",
    ]
    if _is_new_week(previous, payload):
        bits.append("*New week slate*")
    committed = payload.get("committed_this_week")
    if committed:
        bits.append(f"committed `{_escape_mrkdwn(str(committed))}`")
    return "  ·  ".join(bits)


def _alert_lines(alerts: list[Any]) -> list[str]:
    lines: list[str] = []
    for alert in alerts:
        if isinstance(alert, Mapping):
            text = alert.get("message") or alert.get("detail") or alert.get("kind")
        else:
            text = alert
        if not text:
            continue
        lines.append(f":warning: {_escape_mrkdwn(str(text))}")
    return lines


def _action_elements(dashboard_url: str, refresh_url: str) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    if dashboard_url:
        elements.append(_url_button("Dashboard", dashboard_url, "dashboard"))
    if refresh_url:
        elements.append(_url_button("Run refresh", refresh_url, "refresh"))
    return elements


def _raw_text(text: str) -> dict[str, str]:
    return {"type": "raw_text", "text": text}


def _rich_text(text: str, *, bold: bool = False) -> dict[str, Any]:
    element: dict[str, Any] = {"type": "text", "text": text}
    if bold:
        element["style"] = {"bold": True}
    return {
        "type": "rich_text",
        "elements": [{"type": "rich_text_section", "elements": [element]}],
    }


def _url_button(label: str, url: str, action_id: str) -> dict[str, Any]:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "url": url,
        "action_id": action_id,
    }


def _escape_mrkdwn(value: str) -> str:
    for src, dst in _MRKDWN_ESCAPES:
        value = value.replace(src, dst)
    return value


def _is_new_week(previous: Optional[Mapping[str, Any]], current: Mapping[str, Any]) -> bool:
    if not previous:
        return True
    return previous.get("week") != current.get("week")


def _webhook(explicit: Optional[str]) -> Optional[str]:
    load_env()
    value = explicit if explicit is not None else os.getenv(WEBHOOK_ENV)
    if not value:
        return None
    return value.strip() or None


def _post_json(url: str, body: Mapping[str, Any]) -> None:
    response = requests.post(url, json=body, timeout=30)
    response.raise_for_status()


def _failure_message(template: str) -> str:
    run_url = os.environ.get("GITHUB_RUN_URL") or os.environ.get("RUN_URL") or ""
    if "{RUN_URL}" in template:
        msg = template.replace("{RUN_URL}", run_url)
    else:
        msg = template
    if not run_url:
        repo = os.environ.get("GITHUB_REPOSITORY") or ""
        run_id = os.environ.get("GITHUB_RUN_ID") or ""
        if repo and run_id:
            run_url = f"https://github.com/{repo}/actions/runs/{run_id}"
            if "http" not in msg:
                msg = f"{msg} {run_url}".strip()
    return msg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Slack Incoming Webhook helpers")
    parser.add_argument("--failure", metavar="MESSAGE", help="Post a short failure ping")
    args = parser.parse_args(argv)
    if args.failure:
        posted = post_failure(_failure_message(args.failure))
        return 0 if posted or not _webhook(None) else 1
    parser.error("pass --failure MESSAGE")
    return 2


if __name__ == "__main__":
    sys.exit(main())
