import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "survivor_week.json"


def test_fixture_cli_smoke_no_env(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in {"ODDS_API_KEY", "SLACK_WEBHOOK_URL"}}
    env["PYTHONPATH"] = str(REPO)
    web_out = REPO / "web" / "recommendations.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.survivor.run",
            "--fixture",
            str(FIXTURE),
            "--web",
            "--no-slack",
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    data = json.loads(web_out.read_text(encoding="utf-8"))
    assert data["week"] == 1
    assert data["primary"]["team"] == "Buffalo Bills"
    assert "survive_p" in data["primary"]


def test_commit_cli_temp_state(tmp_path):
    import yaml
    from src.survivor.state import load_state

    state_path = tmp_path / "state.yaml"
    state_path.write_text(
        yaml.safe_dump(
            {
                "season": 2026,
                "lives_remaining": 2,
                "used_teams": [],
                "committed": {},
                "notes": "",
                "pool": {"name": "NFL Survivor", "tie_rule": "loss", "last_week": 18},
            }
        ),
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k not in {"ODDS_API_KEY", "SLACK_WEBHOOK_URL"}}
    env["PYTHONPATH"] = str(REPO)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.survivor.run",
            "--commit",
            "Buffalo Bills",
            "--week",
            "1",
            "--state",
            str(state_path),
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    state = load_state(state_path)
    assert state.used_teams == ["Buffalo Bills"]
    assert state.committed[1] == "Buffalo Bills"
