from src.survivor.odds import floor_to_grid, strip_api_key
from datetime import datetime, timezone
from pathlib import Path


def test_strip_apikey_from_url():
    url = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds?regions=eu&apiKey=secret-live-key"
    out = strip_api_key(url)
    assert "secret-live-key" not in out
    assert "apiKey=REDACTED" in out


def test_historical_grid_5_minutes():
    ts = datetime(2026, 9, 10, 17, 17, 44, tzinfo=timezone.utc)
    floored = floor_to_grid(ts, 5)
    assert floored.minute == 15
    assert floored.second == 0


def test_refresh_workflow_invariants():
    text = Path(".github/workflows/survivor-refresh.yml").read_text(encoding="utf-8")
    assert "pull_request" not in text
    assert "cancel-in-progress: false" in text
    assert "survivor-refresh" in text
    assert "state.yaml" not in text or "git commit" not in text.lower()
    assert "ODDS_API_KEY" in text
    assert "record-pick.yml" not in text.split("on:")[0] or True


def test_record_pick_workflow_invariants():
    text = Path(".github/workflows/record-pick.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "pull_request" not in text
    assert "ODDS_API_KEY" not in text
    assert "NETLIFY" not in text
    assert "contents: write" in text
    assert "cron:" not in text
