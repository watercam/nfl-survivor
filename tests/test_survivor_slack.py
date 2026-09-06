from src.settings import load_settings
from src.survivor.alerts import collect_alerts
from src.survivor.slack import format_success
from src.survivor.types import ScoredSide
from datetime import datetime, timezone


def test_slack_record_pick_url_not_run_id():
    from dataclasses import replace

    settings = load_settings()

    settings = replace(settings, github_repo="acme/nfl-survivor")
    payload = {
        "week": 1,
        "lives_remaining": 2,
        "used_teams": [],
        "generated_at": "2026-09-06T16:00:00Z",
        "status": "active",
        "primary": {
            "team": "Buffalo Bills",
            "opponent": "Arizona Cardinals",
            "kickoff": "2026-09-13T17:00:00Z",
            "p_final": 0.78,
            "survive_p": 0.41,
        },
        "greedy_this_week": {"team": "Kansas City Chiefs", "p_final": 0.90},
        "alternatives": [
            {"team": "Buffalo Bills", "survive_p": 0.41},
            {"team": "Kansas City Chiefs", "survive_p": 0.39},
        ],
        "alerts": [{"kind": "new_week_slate"}],
        "record_pick_url": "https://github.com/acme/nfl-survivor/actions/workflows/record-pick.yml",
    }
    text = format_success(payload, settings=settings)
    assert "NFL Survivor week 1 · lives 2 · used 0" in text
    assert "https://github.com/acme/nfl-survivor/actions/workflows/record-pick.yml" in text
    assert "Record pick" in text
    assert "week 1 · suggested Buffalo Bills" in text
    assert "empty Team = lock suggested" in text
    assert "saved Kansas City Chiefs for later" in text
    assert "/actions/runs/" not in text
    run_id = "987654321"
    assert run_id not in text
    assert "survivor-refresh.yml" in text  # optional refresh link, not used as Record pick
    record_line = [ln for ln in text.splitlines() if "Record pick" in ln][0]
    assert "record-pick.yml" in record_line
    assert "survivor-refresh.yml" not in record_line


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
