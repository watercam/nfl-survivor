from pathlib import Path

import yaml

from src.survivor.state import apply_commit, apply_loss, load_state, save_state


def test_commit_updates_used_and_committed(tmp_path: Path):
    path = tmp_path / "state.yaml"
    path.write_text(
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
    state = load_state(path)
    apply_commit(state, "Buffalo Bills", 1)
    save_state(path, state)
    reloaded = load_state(path)
    assert reloaded.used_teams == ["Buffalo Bills"]
    assert reloaded.committed[1] == "Buffalo Bills"
    assert reloaded.lives_remaining == 2


def test_loss_decrements_min_zero(tmp_path: Path):
    path = tmp_path / "state.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "season": 2026,
                "lives_remaining": 1,
                "used_teams": [],
                "committed": {},
                "notes": "",
                "pool": {"name": "NFL Survivor", "tie_rule": "loss", "last_week": 18},
            }
        ),
        encoding="utf-8",
    )
    state = load_state(path)
    apply_loss(state)
    apply_loss(state)
    assert state.lives_remaining == 0
