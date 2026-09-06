from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

WEEK1 = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 8, 16, 0, tzinfo=timezone.utc)

PAIRS_2_14 = [
    (2, "Atlanta Falcons", "Baltimore Ravens"),
    (3, "Carolina Panthers", "Chicago Bears"),
    (4, "Cleveland Browns", "Dallas Cowboys"),
    (5, "Detroit Lions", "Green Bay Packers"),
    (6, "Houston Texans", "Indianapolis Colts"),
    (7, "Jacksonville Jaguars", "Las Vegas Raiders"),
    (8, "Los Angeles Chargers", "Los Angeles Rams"),
    (9, "Miami Dolphins", "Minnesota Vikings"),
    (10, "New England Patriots", "New Orleans Saints"),
    (11, "New York Giants", "New York Jets"),
    (12, "Philadelphia Eagles", "Pittsburgh Steelers"),
    (13, "San Francisco 49ers", "Seattle Seahawks"),
    (14, "Tampa Bay Buccaneers", "Tennessee Titans"),
]


def kickoff_for_week(week: int) -> str:
    dt = WEEK1 + timedelta(days=7 * (week - 1))
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    games = [
        {
            "game_id": "w1-kc",
            "week": 1,
            "home": "Cincinnati Bengals",
            "away": "Kansas City Chiefs",
            "kickoff": kickoff_for_week(1),
            "status": "scheduled",
        },
        {
            "game_id": "w1-buf",
            "week": 1,
            "home": "Arizona Cardinals",
            "away": "Buffalo Bills",
            "kickoff": kickoff_for_week(1),
            "status": "scheduled",
        },
        {
            "game_id": "w1-started",
            "week": 1,
            "home": "Seattle Seahawks",
            "away": "San Francisco 49ers",
            "kickoff": "2026-09-08T00:20:00Z",
            "status": "in",
        },
    ]
    for week, home, away in PAIRS_2_14:
        games.append(
            {
                "game_id": f"w{week}",
                "week": week,
                "home": home,
                "away": away,
                "kickoff": kickoff_for_week(week),
                "status": "scheduled",
            }
        )
    games.append(
        {
            "game_id": "w15-kc",
            "week": 15,
            "home": "Denver Broncos",
            "away": "Kansas City Chiefs",
            "kickoff": kickoff_for_week(15),
            "status": "scheduled",
        }
    )
    games.append(
        {
            "game_id": "w15-was",
            "week": 15,
            "home": "Washington Commanders",
            "away": "Arizona Cardinals",
            "kickoff": kickoff_for_week(15),
            "status": "scheduled",
        }
    )
    t72 = (WEEK1 - timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ")
    current_ts = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshots = [
        {
            "game_id": "w1-kc",
            "home": "Cincinnati Bengals",
            "away": "Kansas City Chiefs",
            "snapshot_ts": current_ts,
            "h2h": {"Kansas City Chiefs": -900, "Cincinnati Bengals": 900},
            "spreads": {"Kansas City Chiefs": -14.0, "Cincinnati Bengals": 14.0},
        },
        {
            "game_id": "w1-kc",
            "home": "Cincinnati Bengals",
            "away": "Kansas City Chiefs",
            "snapshot_ts": t72,
            "h2h": {"Kansas City Chiefs": -850, "Cincinnati Bengals": 850},
            "spreads": {"Kansas City Chiefs": -13.5, "Cincinnati Bengals": 13.5},
        },
        {
            "game_id": "w1-buf",
            "home": "Arizona Cardinals",
            "away": "Buffalo Bills",
            "snapshot_ts": current_ts,
            "h2h": {"Buffalo Bills": -355, "Arizona Cardinals": 355},
            "spreads": {"Buffalo Bills": -6.5, "Arizona Cardinals": 6.5},
        },
        {
            "game_id": "w15-kc",
            "home": "Denver Broncos",
            "away": "Kansas City Chiefs",
            "snapshot_ts": current_ts,
            "h2h": {"Kansas City Chiefs": -900, "Denver Broncos": 900},
            "spreads": {"Kansas City Chiefs": -14.0, "Denver Broncos": 14.0},
        },
        {
            "game_id": "w15-was",
            "home": "Washington Commanders",
            "away": "Arizona Cardinals",
            "snapshot_ts": current_ts,
            "h2h": {"Washington Commanders": -150, "Arizona Cardinals": 130},
            "spreads": {"Washington Commanders": -3.0, "Arizona Cardinals": 3.0},
        },
    ]
    payload = {
        "now": current_ts,
        "week": 1,
        "last_week": 15,
        "games": games,
        "snapshots": snapshots,
    }
    out = Path(__file__).resolve().parent / "fixtures" / "survivor_week.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
