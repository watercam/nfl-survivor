from datetime import datetime, timezone

from src.survivor.alerts import collect_alerts
from src.survivor.slack import (
    format_failure_blocks,
    format_success_blocks,
    format_success_message,
    post_failure,
    post_survivor_update,
)
from src.survivor.types import ScoredSide


def _payload(**overrides):
    base = {
        "week": 1,
        "lives_remaining": 2,
        "used_teams": [],
        "generated_at": "2026-09-06T16:00:00Z",
        "status": "active",
        "calibration": "none",
        "committed_this_week": None,
        "primary": {
            "team": "Buffalo Bills",
            "opponent": "Arizona Cardinals",
            "kickoff": "2026-09-13T17:00:00Z",
            "p_final": 0.78,
            "survive_p": 0.41,
            "source": "market",
        },
        "greedy_this_week": {"team": "Kansas City Chiefs", "p_final": 0.90},
        "alternatives": [
            {
                "team": "Buffalo Bills",
                "opponent": "Arizona Cardinals",
                "p_final": 0.78,
                "survive_p": 0.41,
                "source": "market",
            },
            {
                "team": "Kansas City Chiefs",
                "opponent": "Los Angeles Chargers",
                "p_final": 0.90,
                "survive_p": 0.39,
                "source": "market",
            },
            {
                "team": "Philadelphia Eagles",
                "opponent": "Dallas Cowboys",
                "p_final": 0.72,
                "survive_p": 0.37,
                "source": "ratings",
            },
        ],
        "alerts": [],
    }
    base.update(overrides)
    return base


def test_success_fallback_text_has_week_lives_used_matchup() -> None:
    text = format_success_message(
        _payload(),
        previous={"week": 1},
        dashboard_url="https://nfl-survivor.netlify.app",
        refresh_url="https://github.com/acme/nfl-survivor/actions/workflows/survivor-refresh.yml",
    )
    assert text == (
        "NFL Survivor week 1 · lives 2 · used 0 · Buffalo Bills vs Arizona Cardinals"
    )
    assert "dashboard:" not in text
    assert "Run refresh:" not in text


def test_success_fallback_appends_new_week_slate() -> None:
    assert " · new week slate" in format_success_message(_payload(), previous=None)
    assert " · new week slate" in format_success_message(_payload(week=2), previous={"week": 1})
    assert "new week slate" not in format_success_message(_payload(), previous={"week": 1})


def test_success_blocks_order_header_context_primary_table_actions() -> None:
    blocks = format_success_blocks(
        _payload(),
        previous={"week": 1},
        dashboard_url="https://nfl-survivor.netlify.app",
        refresh_url="https://github.com/acme/nfl-survivor/actions/workflows/survivor-refresh.yml",
    )
    assert [block["type"] for block in blocks] == [
        "header",
        "context",
        "section",
        "table",
        "actions",
    ]
    assert blocks[0]["text"]["text"] == "NFL Survivor · Week 1"
    context = blocks[1]["elements"][0]["text"]
    assert "lives `2`" in context
    assert "used `0`" in context
    assert "status `active`" in context
    assert "calibration `none`" in context
    assert "generated_at `2026-09-06T16:00:00Z`" in context
    assert "New week slate" not in context
    primary = blocks[2]
    assert primary["expand"] is True
    assert "*Buffalo Bills* vs Arizona Cardinals" in primary["text"]["text"]
    assert "win 78%" in primary["text"]["text"]
    assert "survive 41%" in primary["text"]["text"]
    assert "_Saved Kansas City Chiefs (this-week win 90%) for later._" in primary["text"]["text"]
    table = blocks[3]
    assert [cell["text"] for cell in table["rows"][0]] == [
        "Rank",
        "Team",
        "Opp",
        "Win",
        "Survive",
        "Source",
    ]
    chiefs = table["rows"][1]
    assert chiefs[0]["text"] == "1"
    assert chiefs[1]["elements"][0]["elements"][0]["text"] == "Kansas City Chiefs"
    assert chiefs[1]["elements"][0]["elements"][0]["style"]["bold"] is True
    assert chiefs[2]["text"] == "Los Angeles Chargers"
    assert chiefs[3]["text"] == "90%"
    assert chiefs[4]["text"] == "39%"
    assert chiefs[5]["text"] == "market"
    buttons = {el["action_id"]: el["url"] for el in blocks[4]["elements"]}
    assert buttons["dashboard"] == "https://nfl-survivor.netlify.app"
    assert (
        buttons["refresh"]
        == "https://github.com/acme/nfl-survivor/actions/workflows/survivor-refresh.yml"
    )
    assert blocks[4]["elements"][0]["text"]["text"] == "Dashboard"
    assert blocks[4]["elements"][1]["text"]["text"] == "Run refresh"


def test_committed_and_new_week_and_alerts_are_in_blocks() -> None:
    payload = _payload(
        week=2,
        committed_this_week="Buffalo Bills",
        alerts=[{"kind": "pick_change", "message": "Chiefs → Bills"}],
    )
    blocks = format_success_blocks(payload, previous={"week": 1})
    assert [block["type"] for block in blocks] == ["header", "context", "section", "table", "section"]
    context = blocks[1]["elements"][0]["text"]
    assert "*New week slate*" in context
    assert "committed `Buffalo Bills`" in context
    assert blocks[4]["text"]["text"].startswith("*Alerts*")
    assert ":warning: Chiefs → Bills" in blocks[4]["text"]["text"]


def test_missing_stats_are_empty_table_cells() -> None:
    payload = _payload(
        alternatives=[
            {"team": "Dallas Cowboys", "opponent": "New York Giants"},
        ]
    )
    row = format_success_blocks(payload, previous={"week": 1})[3]["rows"][1]
    assert row[2]["text"] == "New York Giants"
    assert row[3]["text"] == ""
    assert row[4]["text"] == ""
    assert row[5]["text"] == ""


def test_table_keeps_team_name_characters() -> None:
    payload = _payload(
        alternatives=[
            {
                "team": "Texas A&M",
                "opponent": "SMU <FBS>",
                "p_final": 0.61,
            }
        ]
    )
    row = format_success_blocks(payload, previous={"week": 1})[3]["rows"][1]
    assert row[1]["elements"][0]["elements"][0]["text"] == "Texas A&M"
    assert row[2]["text"] == "SMU <FBS>"


def test_six_alternatives_split_into_two_tables(monkeypatch) -> None:
    monkeypatch.setattr("src.survivor.slack.SLACK_ALT_LIMIT", 10)
    alts = [
        {"team": f"Team{n}", "opponent": f"Opp{n}", "p_final": 0.5, "survive_p": 0.2, "source": "prior"}
        for n in range(1, 7)
    ]
    blocks = format_success_blocks(_payload(alternatives=alts), previous={"week": 1})
    tables = [block for block in blocks if block["type"] == "table"]
    assert len(tables) == 2
    assert [row[0]["text"] for row in tables[0]["rows"][1:]] == ["1", "2", "3", "4", "5"]
    assert [row[0]["text"] for row in tables[1]["rows"][1:]] == ["6"]
    assert [cell["text"] for cell in tables[1]["rows"][0]] == [
        "Rank",
        "Team",
        "Opp",
        "Win",
        "Survive",
        "Source",
    ]


def test_slack_top_three_and_skips_dogs() -> None:
    alts = [
        {"team": "Kansas City Chiefs", "opponent": "Bengals", "p_final": 0.90, "survive_p": 0.39},
        {"team": "Philadelphia Eagles", "opponent": "Cowboys", "p_final": 0.72, "survive_p": 0.37},
        {"team": "Detroit Lions", "opponent": "Packers", "p_final": 0.70, "survive_p": 0.36},
        {"team": "Minnesota Vikings", "opponent": "Bears", "p_final": 0.65, "survive_p": 0.35},
        {"team": "Arizona Cardinals", "opponent": "Bills", "p_final": 0.22, "survive_p": 0.002},
        {"team": "Cincinnati Bengals", "opponent": "Chiefs", "p_final": 0.10, "survive_p": 0.001},
    ]
    table = [b for b in format_success_blocks(_payload(alternatives=alts), previous={"week": 1}) if b["type"] == "table"][0]
    teams = [row[1]["elements"][0]["elements"][0]["text"] for row in table["rows"][1:]]
    assert teams == ["Kansas City Chiefs", "Philadelphia Eagles", "Detroit Lions"]
    assert "Arizona Cardinals" not in teams
    assert "Cincinnati Bengals" not in teams


def test_survive_p_keeps_sub_percent_precision() -> None:
    payload = _payload(
        primary={
            "team": "Buffalo Bills",
            "opponent": "Arizona Cardinals",
            "kickoff": "2026-09-13T17:00:00Z",
            "p_final": 0.78,
            "survive_p": 0.00638,
            "source": "market",
        }
    )
    text = format_success_blocks(payload, previous={"week": 1})[2]["text"]["text"]
    assert "survive 0.64%" in text
    assert "survive 1%" not in text
    assert "survive 0%" not in text


def test_buttons_omitted_when_urls_empty() -> None:
    blocks = format_success_blocks(_payload(), previous={"week": 1})
    assert [block["type"] for block in blocks] == ["header", "context", "section", "table"]


def test_eliminated_posts_without_primary_table() -> None:
    payload = _payload(
        status="eliminated",
        lives_remaining=0,
        primary=None,
        greedy_this_week=None,
        alternatives=[],
        alerts=[{"kind": "eliminated", "detail": "lives_remaining is 0"}],
    )
    text = format_success_message(payload, previous={"week": 1})
    assert "NFL Survivor week 1 · lives 0 · used 0 · no pick" == text
    blocks = format_success_blocks(
        payload,
        previous={"week": 1},
        dashboard_url="https://nfl-survivor.netlify.app",
    )
    types = [block["type"] for block in blocks]
    assert types == ["header", "context", "section", "section", "actions"]
    assert "table" not in types
    assert "no pick" in blocks[2]["text"]["text"].lower()
    assert ":warning: lives_remaining is 0" in blocks[3]["text"]["text"]


def test_failure_blocks_escape_mrkdwn() -> None:
    blocks = format_failure_blocks("failed: https://example.com?a=1&b=2 <run>")
    assert blocks[0]["text"]["text"] == "NFL Survivor refresh failed"
    assert blocks[1]["text"]["text"] == "failed: https://example.com?a=1&amp;b=2 &lt;run&gt;"


def test_post_skips_without_webhook(monkeypatch) -> None:
    monkeypatch.setattr("src.survivor.slack.load_env", lambda: None)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

    def boom(*_args, **_kwargs):
        raise AssertionError("must not POST")

    monkeypatch.setattr("src.survivor.slack.requests.post", boom)
    assert post_survivor_update(_payload(), webhook_url="") is False
    assert post_failure("failed", webhook_url=None) is False


def test_post_sends_blocks_payload(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("src.survivor.slack.requests.post", fake_post)
    assert post_survivor_update(
        _payload(),
        previous={"week": 1},
        dashboard_url="https://nfl-survivor.netlify.app",
        webhook_url="https://hooks.slack.com/services/T/B/X",
    )
    body = captured["json"]
    assert captured["url"] == "https://hooks.slack.com/services/T/B/X"
    assert captured["timeout"] == 30
    assert body["text"] == (
        "NFL Survivor week 1 · lives 2 · used 0 · Buffalo Bills vs Arizona Cardinals"
    )
    assert body["unfurl_links"] is False
    assert [block["type"] for block in body["blocks"]] == [
        "header",
        "context",
        "section",
        "table",
        "actions",
    ]
    assert post_failure("boom", webhook_url="https://hooks.slack.com/services/T/B/X")
    fail = captured["json"]
    assert fail["text"] == "boom"
    assert fail["unfurl_links"] is False
    assert fail["blocks"][0]["text"]["text"] == "NFL Survivor refresh failed"


def test_alerts_pick_change_and_new_week():
    now = datetime(2026, 9, 8, 16, tzinfo=timezone.utc)
    primary = ScoredSide(
        team="Buffalo Bills",
        opponent="Arizona Cardinals",
        is_home=False,
        week=1,
        game_id="g",
        kickoff=datetime(2026, 9, 13, 17, tzinfo=timezone.utc),
        p_current=0.78,
        spread_move=0.0,
        adj=0.0,
        p_final=0.78,
        source="market",
        survive_p=0.4,
    )
    a = collect_alerts(
        week=1,
        now=now,
        primary=primary,
        previous=None,
        survive_p=0.4,
        locked_team=None,
        status="active",
        flags=[],
    )
    assert any(x["kind"] == "new_week_slate" for x in a)
    b = collect_alerts(
        week=1,
        now=now,
        primary=primary,
        previous={"week": 1, "primary": {"team": "Kansas City Chiefs", "survive_p": 0.5}},
        survive_p=0.4,
        locked_team=None,
        status="active",
        flags=[],
    )
    kinds = {x["kind"] for x in b}
    assert "pick_change" in kinds
    assert "survive_drop" in kinds
