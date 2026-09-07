from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path | None = None) -> None:
    """Fill empty/missing os.environ keys from a local .env (never overrides set vars)."""
    env_path = path or (REPO_ROOT / ".env")
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if not key:
            continue
        current = os.environ.get(key)
        if current is None or current == "":
            os.environ[key] = value


def _load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass(frozen=True)
class OddsApiSettings:
    sport: str
    markets: tuple[str, ...]
    regions: tuple[str, ...]
    preferred_bookmaker: str
    allow_book_fallback: bool
    odds_format: str
    snapshot_grid_minutes: int
    host: str = "https://api.the-odds-api.com"


@dataclass(frozen=True)
class CalibrationSettings:
    source: str
    clamp_min: float
    clamp_max: float
    max_adjustment: float
    matrix_csv: str


@dataclass(frozen=True)
class Settings:
    reference_hours: int
    odds_api: OddsApiSettings
    calibration: CalibrationSettings
    espn_scoreboard_url: str
    dashboard_url: str
    last_week: int
    home_prior: float
    github_repo: str
    record_pick_workflow: str
    slack_heartbeat: str
    aliases: list[dict[str, str]]
    odds_api_key: str | None = None
    config_dir: Path = field(default_factory=lambda: REPO_ROOT / "config")

    @property
    def state_path(self) -> Path:
        return self.config_dir / "state.yaml"

    def record_pick_url(self) -> str | None:
        repo = (self.github_repo or os.environ.get("GITHUB_REPOSITORY") or "").strip()
        if not repo:
            return None
        wf = self.record_pick_workflow or "record-pick.yml"
        return f"https://github.com/{repo}/actions/workflows/{wf}"

    def refresh_workflow_url(self) -> str | None:
        repo = (self.github_repo or os.environ.get("GITHUB_REPOSITORY") or "").strip()
        if not repo:
            return None
        return f"https://github.com/{repo}/actions/workflows/survivor-refresh.yml"


def load_settings(
    *,
    config_dir: Path | None = None,
    odds_api_key: str | None = None,
) -> Settings:
    config_dir = config_dir or (REPO_ROOT / "config")
    survivor = _load_yaml(config_dir / "survivor.yaml")
    aliases = _load_yaml(config_dir / "team_aliases.yaml") or []
    odds = survivor["odds_api"]
    cal = survivor["calibration"]
    slate = survivor["slate"]
    ops = survivor["ops"]
    slack = survivor.get("slack") or {}
    key = odds_api_key if odds_api_key is not None else os.environ.get("ODDS_API_KEY")
    return Settings(
        reference_hours=int(survivor["horizons"]["reference_hours"]),
        odds_api=OddsApiSettings(
            sport=odds["sport"],
            markets=tuple(odds["markets"]),
            regions=tuple(odds["regions"]),
            preferred_bookmaker=odds["preferred_bookmaker"],
            allow_book_fallback=bool(odds["allow_book_fallback"]),
            odds_format=odds["odds_format"],
            snapshot_grid_minutes=int(odds["snapshot_grid_minutes"]),
        ),
        calibration=CalibrationSettings(
            source=str(cal["source"]),
            clamp_min=float(cal["clamp_min"]),
            clamp_max=float(cal["clamp_max"]),
            max_adjustment=float(cal["max_adjustment"]),
            matrix_csv=str(cal.get("matrix_csv") or ""),
        ),
        espn_scoreboard_url=slate["espn_scoreboard_url"],
        dashboard_url=str(slate.get("dashboard_url") or ""),
        last_week=int(slate["last_week"]),
        home_prior=float(slate["home_prior"]),
        github_repo=str(ops.get("github_repo") or ""),
        record_pick_workflow=str(ops.get("record_pick_workflow") or "record-pick.yml"),
        slack_heartbeat=str(slack.get("heartbeat") or "always"),
        aliases=list(aliases),
        odds_api_key=key or None,
        config_dir=config_dir,
    )


def alias_index(aliases: list[dict[str, str]]) -> dict[str, str]:
    """Exact match only: canonical, espn_team, odds_team, abbr → canonical."""
    out: dict[str, str] = {}
    for row in aliases:
        canonical = row["canonical"]
        for key in ("canonical", "espn_team", "odds_team", "abbr"):
            val = (row.get(key) or "").strip()
            if val:
                out[val] = canonical
    return out


def canonicalize(name: str, aliases: list[dict[str, str]]) -> str | None:
    return alias_index(aliases).get(name.strip()) if name else None


def names_for_canonical(canonical: str, aliases: list[dict[str, str]]) -> list[str]:
    for row in aliases:
        if row["canonical"] == canonical:
            vals = [row.get("canonical"), row.get("espn_team"), row.get("odds_team"), row.get("abbr")]
            return [v for v in vals if v]
    return [canonical]


def abbr_for(canonical: str, aliases: list[dict[str, str]]) -> str:
    for row in aliases:
        if row["canonical"] == canonical:
            return row.get("abbr") or canonical
    return canonical
