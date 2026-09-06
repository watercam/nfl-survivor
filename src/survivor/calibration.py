from __future__ import annotations

import csv
from pathlib import Path


def handwritten_adjustment(delta_spread: float) -> float:
    d = float(delta_spread)
    if d > 2.5:
        adj = 0.03
    elif 1.0 <= d <= 2.5:
        adj = 0.015
    elif -0.5 <= d <= 0.5:
        adj = 0.0
    elif -2.5 <= d <= -1.0:
        adj = -0.015
    elif d < -2.5:
        adj = -0.03
    else:
        # gaps 0.5–1.0 and −1.0…−0.5
        adj = 0.0
    return max(-0.03, min(0.03, adj))


def matrix_csv_adjustment(delta_spread: float, current_probability: float, path: Path) -> float:
    if not path.is_file():
        return 0.0
    # Optional lookup: rows labeled by rounded spread move, columns by p bucket.
    p_bucket = f"{round(current_probability, 2):.2f}"
    move_key = f"{round(delta_spread, 1):.1f}"
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if str(row.get("spread_move") or "") == move_key:
                raw = row.get(p_bucket)
                if raw in (None, ""):
                    return 0.0
                try:
                    return float(raw)
                except ValueError:
                    return 0.0
    return 0.0


def movement_adjustment(
    current_probability: float,
    delta_spread: float,
    *,
    source: str = "none",
    matrix_csv: str = "",
) -> float:
    if source == "none":
        return 0.0
    if source == "handwritten":
        return handwritten_adjustment(delta_spread)
    if source == "matrix_csv":
        if not matrix_csv:
            return 0.0
        return matrix_csv_adjustment(delta_spread, current_probability, Path(matrix_csv))
    return 0.0
