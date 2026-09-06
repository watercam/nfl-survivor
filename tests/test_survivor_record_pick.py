import json
from pathlib import Path

import yaml

from src.survivor.record_pick import record_pick
from src.survivor.state import load_state


def _state_file(tmp_path: Path, committed=None) -> Path:
    path = tmp_path / "state.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "season": 2026,
                "lives_remaining": 2,
                "used_teams": list((committed or {}).values()),
                "committed": {str(k): v for k, v in (committed or {}).items()},
                "notes": "",
                "pool": {"name": "NFL Survivor", "tie_rule": "loss", "last_week": 18},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_empty_team_locks_dashboard_primary(tmp_path: Path):
    state_path = _state_file(tmp_path)
    dash = {
        "week": 3,
        "primary": {"team": "Buffalo Bills"},
    }
    code, msg = record_pick(
        team="",
        week="",
        loss=False,
        replace=False,
        state_path=state_path,
        dashboard_json=dash,
    )
    assert code == 0
    state = load_state(state_path)
    assert state.committed[3] == "Buffalo Bills"
    assert "Buffalo Bills" in state.used_teams


def test_empty_team_does_not_overwrite_existing(tmp_path: Path):
    state_path = _state_file(tmp_path, committed={3: "Dallas Cowboys"})
    dash = {"week": 3, "primary": {"team": "Buffalo Bills"}}
    code, msg = record_pick(
        team="",
        week=3,
        loss=False,
        replace=False,
        state_path=state_path,
        dashboard_json=dash,
    )
    assert code == 0
    state = load_state(state_path)
    assert state.committed[3] == "Dallas Cowboys"


def test_unmapped_team_fails(tmp_path: Path):
    state_path = _state_file(tmp_path)
    code, msg = record_pick(
        team="Springfield Atoms",
        week=1,
        loss=False,
        replace=False,
        state_path=state_path,
        dashboard_json={"week": 1, "primary": {"team": "Buffalo Bills"}},
    )
    assert code == 1
    assert "unmapped" in msg.lower()


def test_replace_false_refuses_conflict(tmp_path: Path):
    state_path = _state_file(tmp_path, committed={1: "Dallas Cowboys"})
    code, msg = record_pick(
        team="BUF",
        week=1,
        loss=False,
        replace=False,
        state_path=state_path,
        dashboard_json={"week": 1},
    )
    assert code == 1
    assert "already locked" in msg.lower() or "replace" in msg.lower()
    state = load_state(state_path)
    assert state.committed[1] == "Dallas Cowboys"
