import os
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.settings import load_dotenv
from src.survivor.odds import floor_to_grid, strip_api_key

WORKFLOW_DIR = Path(".github/workflows")
_GH_EXPR = re.compile(r"\$\{\{.*?\}\}")
_RUN_LINE = re.compile(r"^(\s*)run:\s*(.*)$")


def _workflow_on(data: dict) -> dict:
    # PyYAML 1.1 loads the GitHub key `on:` as boolean True.
    on_block = data.get("on", data.get(True))
    assert isinstance(on_block, dict)
    return on_block


def _unquoted_run_brace_offenders(text: str) -> list[str]:
    """GitHub Actions treats `{` in a plain `run:` scalar as a flow mapping."""
    offenders: list[str] = []
    for i, line in enumerate(text.splitlines(), start=1):
        match = _RUN_LINE.match(line)
        if match is None:
            continue
        rest = match.group(2)
        if rest.startswith("|") or rest.startswith(">"):
            continue
        if (rest.startswith('"') and rest.endswith('"')) or (
            rest.startswith("'") and rest.endswith("'")
        ):
            continue
        if "{" in _GH_EXPR.sub("", rest):
            offenders.append(f"{i}: {line.rstrip()}")
    return offenders


def test_unquoted_run_brace_rule_catches_github_invalid_yaml():
    bad = '        run: python -m src.survivor.slack --failure "failed: ${RUN_URL}"\n'
    assert _unquoted_run_brace_offenders(bad)
    block = '        run: |\n          python -m src.survivor.slack --failure "failed: {RUN_URL}"\n'
    assert not _unquoted_run_brace_offenders(block)


def test_load_dotenv_fills_empty_only(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ODDS_API_KEY=fromfile\nKEEP=keepme\n", encoding="utf-8")
    monkeypatch.setenv("KEEP", "already")
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    load_dotenv(env_file)
    assert os.environ["ODDS_API_KEY"] == "fromfile"
    assert os.environ["KEEP"] == "already"


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
    path = WORKFLOW_DIR / "survivor-refresh.yml"
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert data["name"] == "Survivor refresh"
    assert "workflow_dispatch" in _workflow_on(data)
    assert "pull_request" not in text
    assert "cancel-in-progress: false" in text
    assert "survivor-refresh" in text
    assert "state.yaml" not in text or "git commit" not in text.lower()
    assert "ODDS_API_KEY" in text
    assert "{RUN_URL}" in text
    assert not _unquoted_run_brace_offenders(text)


def test_record_pick_workflow_invariants():
    path = WORKFLOW_DIR / "record-pick.yml"
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert data["name"] == "Record pick"
    assert "workflow_dispatch" in _workflow_on(data)
    assert "pull_request" not in text
    assert "ODDS_API_KEY" not in text
    assert "NETLIFY" not in text
    assert "contents: write" in text
    assert "cron:" not in text
    assert not _unquoted_run_brace_offenders(text)
