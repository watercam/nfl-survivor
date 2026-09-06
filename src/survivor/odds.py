from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from src.settings import Settings, canonicalize
from src.survivor.slate import parse_utc
from src.survivor.types import Snapshot

ODDS_HOST = "https://api.the-odds-api.com"


def strip_api_key(url: str) -> str:
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() == "apikey":
            query.append((key, "REDACTED"))
        else:
            query.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def floor_to_grid(ts: datetime, minutes: int) -> datetime:
    ts = ts.astimezone(timezone.utc)
    discard = ts.minute % minutes
    ts = ts.replace(second=0, microsecond=0) - timedelta(minutes=discard)
    return ts


def _pinnacle_book(event: dict[str, Any], *, allow_fallback: bool) -> dict[str, Any] | None:
    books = event.get("bookmakers") or []
    for b in books:
        if str(b.get("key") or "").lower() == "pinnacle":
            return b
    if allow_fallback and books:
        return books[0]
    return None


def _market_outcomes(book: dict[str, Any], key: str) -> list[dict[str, Any]]:
    for m in book.get("markets") or []:
        if m.get("key") == key:
            return list(m.get("outcomes") or [])
    return []


def odds_event_to_snapshot(
    event: dict[str, Any],
    *,
    snapshot_ts: datetime,
    allow_book_fallback: bool,
) -> Snapshot | None:
    book = _pinnacle_book(event, allow_fallback=allow_book_fallback)
    if book is None:
        return None
    home = event.get("home_team") or ""
    away = event.get("away_team") or ""
    h2h: dict[str, int] = {}
    for o in _market_outcomes(book, "h2h"):
        name = o.get("name")
        price = o.get("price")
        if name is None or price is None:
            continue
        h2h[str(name)] = int(price)
    spreads: dict[str, float] = {}
    for o in _market_outcomes(book, "spreads"):
        name = o.get("name")
        point = o.get("point")
        if name is None or point is None:
            continue
        spreads[str(name)] = float(point)
    return Snapshot(
        snapshot_ts=snapshot_ts,
        home=str(home),
        away=str(away),
        game_id=str(event.get("id") or "") or None,
        h2h=h2h,
        spreads=spreads,
    )


class OddsClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self._owns = client is None
        self.client = client or httpx.Client(timeout=30.0)
        self._historical_cache: dict[str, list[dict[str, Any]]] = {}

    def close(self) -> None:
        if self._owns:
            self.client.close()

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        key = self.settings.odds_api_key
        if not key:
            raise RuntimeError("ODDS_API_KEY is required for live odds")
        params = {**params, "apiKey": key}
        url = f"{ODDS_HOST}{path}"
        try:
            resp = self.client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            raise RuntimeError(f"Odds API request failed: {strip_api_key(url)}") from exc

    def fetch_current(self) -> list[dict[str, Any]]:
        o = self.settings.odds_api
        data = self._get(
            f"/v4/sports/{o.sport}/odds",
            {
                "regions": ",".join(o.regions),
                "markets": ",".join(o.markets),
                "bookmakers": o.preferred_bookmaker,
                "oddsFormat": o.odds_format,
            },
        )
        return list(data or [])

    def fetch_historical(self, at: datetime) -> list[dict[str, Any]]:
        o = self.settings.odds_api
        grid = floor_to_grid(at, o.snapshot_grid_minutes)
        date = grid.strftime("%Y-%m-%dT%H:%M:%SZ")
        if date in self._historical_cache:
            return self._historical_cache[date]
        payload = self._get(
            f"/v4/historical/sports/{o.sport}/odds",
            {
                "regions": ",".join(o.regions),
                "markets": ",".join(o.markets),
                "bookmakers": o.preferred_bookmaker,
                "oddsFormat": o.odds_format,
                "date": date,
            },
        )
        # Historical endpoint wraps data
        if isinstance(payload, dict) and "data" in payload:
            events = list(payload.get("data") or [])
        else:
            events = list(payload or [])
        self._historical_cache[date] = events
        return events

    def snapshots_for_slate(
        self,
        *,
        this_week_kickoffs: list[datetime],
        now: datetime,
        reference_hours: int,
    ) -> list[Snapshot]:
        allow = self.settings.odds_api.allow_book_fallback
        snaps: list[Snapshot] = []
        current_events = self.fetch_current()
        current_ts = now
        for ev in current_events:
            snap = odds_event_to_snapshot(ev, snapshot_ts=current_ts, allow_book_fallback=allow)
            if snap:
                snaps.append(snap)
        seen_dates: set[str] = set()
        for kickoff in this_week_kickoffs:
            t72 = kickoff - timedelta(hours=reference_hours)
            if t72 > now:
                continue
            grid = floor_to_grid(t72, self.settings.odds_api.snapshot_grid_minutes)
            date = grid.strftime("%Y-%m-%dT%H:%M:%SZ")
            if date in seen_dates:
                continue
            seen_dates.add(date)
            for ev in self.fetch_historical(t72):
                snap = odds_event_to_snapshot(ev, snapshot_ts=grid, allow_book_fallback=allow)
                if snap:
                    snaps.append(snap)
        return snaps


def match_snapshots(
    snapshots: list[Snapshot],
    *,
    home: str,
    away: str,
    aliases: list[dict[str, str]],
    game_id: str | None = None,
) -> list[Snapshot]:
    home_c = canonicalize(home, aliases) or home
    away_c = canonicalize(away, aliases) or away
    matched: list[Snapshot] = []
    for s in snapshots:
        if game_id and s.game_id and s.game_id == game_id:
            matched.append(s)
            continue
        sh = canonicalize(s.home, aliases) or s.home
        sa = canonicalize(s.away, aliases) or s.away
        if {sh, sa} == {home_c, away_c}:
            matched.append(s)
    return matched
