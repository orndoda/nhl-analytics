"""Build and maintain a SQLite database of NHL play-by-play data.

Covers every game from the 2013-14 season through today, and exposes
functions to pull newly completed games as the season progresses.

Typical usage:

    from nhlpy import NHLClient
    from src.utils.dataloading import backfill, update_latest

    client = NHLClient()
    backfill(client)          # one-time full historical load
    update_latest(client)     # run periodically to pick up new games

Can also be run as a script:

    python -m src.utils.dataloading backfill
    python -m src.utils.dataloading update
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

import pandas as pd
from nhlpy import NHLClient
from nhlpy.http_client import (
    NHLApiException,
    RateLimitExceededException,
    ResourceNotFoundException,
    ServerErrorException,
)
from tqdm.auto import tqdm

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "nhl_pbp.sqlite"

# First regular-season/preseason games of the 2013-14 campaign start in mid-September 2013.
EARLIEST_SCHEDULE_DATE = "2013-09-01"

# gameType: 1 = preseason, 2 = regular season, 3 = playoffs
DEFAULT_GAME_TYPES = (2, 3)

# gameState values that indicate a game is officially over and its play-by-play is stable.
FINAL_GAME_STATES = {"OFF", "FINAL"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id             INTEGER PRIMARY KEY,
    season              INTEGER,
    game_type           INTEGER,
    game_date           TEXT,
    start_time_utc      TEXT,
    venue               TEXT,
    away_team_id        INTEGER,
    away_team_abbrev    TEXT,
    away_score          INTEGER,
    home_team_id        INTEGER,
    home_team_abbrev    TEXT,
    home_score          INTEGER,
    game_state          TEXT,
    game_schedule_state TEXT,
    final_period_type   TEXT,
    periods_played      INTEGER,
    updated_at          TEXT
);

CREATE TABLE IF NOT EXISTS plays (
    game_id                 INTEGER,
    event_id                INTEGER,
    sort_order               INTEGER,
    period                   INTEGER,
    period_type              TEXT,
    time_in_period           TEXT,
    time_remaining           TEXT,
    situation_code           TEXT,
    home_team_defending_side TEXT,
    type_code                INTEGER,
    type_desc_key            TEXT,
    x_coord                  REAL,
    y_coord                  REAL,
    zone_code                TEXT,
    event_owner_team_id      INTEGER,
    shot_type                TEXT,
    reason                   TEXT,
    secondary_reason         TEXT,
    scoring_player_id        INTEGER,
    scoring_player_total     INTEGER,
    assist1_player_id        INTEGER,
    assist1_player_total     INTEGER,
    assist2_player_id        INTEGER,
    assist2_player_total     INTEGER,
    goalie_in_net_id         INTEGER,
    shooting_player_id       INTEGER,
    blocking_player_id       INTEGER,
    hitting_player_id        INTEGER,
    hittee_player_id         INTEGER,
    winning_player_id        INTEGER,
    losing_player_id         INTEGER,
    player_id                INTEGER,
    committed_by_player_id   INTEGER,
    drawn_by_player_id       INTEGER,
    served_by_player_id      INTEGER,
    penalty_severity         TEXT,
    penalty_desc_key         TEXT,
    penalty_duration         INTEGER,
    away_score               INTEGER,
    home_score               INTEGER,
    away_sog                 INTEGER,
    home_sog                 INTEGER,
    PRIMARY KEY (game_id, event_id)
);

CREATE TABLE IF NOT EXISTS roster_spots (
    game_id        INTEGER,
    player_id      INTEGER,
    team_id        INTEGER,
    first_name     TEXT,
    last_name      TEXT,
    sweater_number INTEGER,
    position_code  TEXT,
    PRIMARY KEY (game_id, player_id)
);

CREATE INDEX IF NOT EXISTS idx_games_season ON games (season);
CREATE INDEX IF NOT EXISTS idx_games_date ON games (game_date);
CREATE INDEX IF NOT EXISTS idx_plays_type ON plays (type_desc_key);
"""

# Errors worth retrying: transient rate limiting / server hiccups.
_RETRYABLE_EXCEPTIONS = (RateLimitExceededException, ServerErrorException)


# --------------------------------------------------------------------------- #
# Connection / schema
# --------------------------------------------------------------------------- #

def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (creating if necessary) the play-by-play SQLite database."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


# --------------------------------------------------------------------------- #
# Retry helper
# --------------------------------------------------------------------------- #

def _call_with_retry(fn: Callable, *args, max_retries: int = 5, base_delay: float = 1.5, **kwargs):
    """Call `fn`, retrying with exponential backoff on rate-limit/server errors."""
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except _RETRYABLE_EXCEPTIONS:
            if attempt == max_retries:
                raise
            time.sleep(base_delay * (2 ** attempt) + random.uniform(0, 0.5))


# --------------------------------------------------------------------------- #
# Flattening helpers: raw NHL API JSON -> flat row dicts
# --------------------------------------------------------------------------- #

def _flatten_game(payload: dict) -> dict:
    away = payload.get("awayTeam") or {}
    home = payload.get("homeTeam") or {}
    period_descriptor = payload.get("periodDescriptor") or {}
    outcome = payload.get("gameOutcome") or {}
    venue = payload.get("venue") or {}
    return {
        "game_id": int(payload["id"]),
        "season": payload.get("season"),
        "game_type": payload.get("gameType"),
        "game_date": payload.get("gameDate"),
        "start_time_utc": payload.get("startTimeUTC"),
        "venue": venue.get("default"),
        "away_team_id": away.get("id"),
        "away_team_abbrev": away.get("abbrev"),
        "away_score": away.get("score"),
        "home_team_id": home.get("id"),
        "home_team_abbrev": home.get("abbrev"),
        "home_score": home.get("score"),
        "game_state": payload.get("gameState"),
        "game_schedule_state": payload.get("gameScheduleState"),
        "final_period_type": outcome.get("lastPeriodType"),
        "periods_played": period_descriptor.get("number"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _flatten_play(game_id: int, play: dict) -> dict:
    period = play.get("periodDescriptor") or {}
    details = play.get("details") or {}
    return {
        "game_id": game_id,
        "event_id": play.get("eventId"),
        "sort_order": play.get("sortOrder"),
        "period": period.get("number"),
        "period_type": period.get("periodType"),
        "time_in_period": play.get("timeInPeriod"),
        "time_remaining": play.get("timeRemaining"),
        "situation_code": play.get("situationCode"),
        "home_team_defending_side": play.get("homeTeamDefendingSide"),
        "type_code": play.get("typeCode"),
        "type_desc_key": play.get("typeDescKey"),
        "x_coord": details.get("xCoord"),
        "y_coord": details.get("yCoord"),
        "zone_code": details.get("zoneCode"),
        "event_owner_team_id": details.get("eventOwnerTeamId"),
        "shot_type": details.get("shotType"),
        "reason": details.get("reason"),
        "secondary_reason": details.get("secondaryReason"),
        "scoring_player_id": details.get("scoringPlayerId"),
        "scoring_player_total": details.get("scoringPlayerTotal"),
        "assist1_player_id": details.get("assist1PlayerId"),
        "assist1_player_total": details.get("assist1PlayerTotal"),
        "assist2_player_id": details.get("assist2PlayerId"),
        "assist2_player_total": details.get("assist2PlayerTotal"),
        "goalie_in_net_id": details.get("goalieInNetId"),
        "shooting_player_id": details.get("shootingPlayerId"),
        "blocking_player_id": details.get("blockingPlayerId"),
        "hitting_player_id": details.get("hittingPlayerId"),
        "hittee_player_id": details.get("hitteePlayerId"),
        "winning_player_id": details.get("winningPlayerId"),
        "losing_player_id": details.get("losingPlayerId"),
        "player_id": details.get("playerId"),
        "committed_by_player_id": details.get("committedByPlayerId"),
        "drawn_by_player_id": details.get("drawnByPlayerId"),
        "served_by_player_id": details.get("servedByPlayerId"),
        "penalty_severity": details.get("typeCode"),
        "penalty_desc_key": details.get("descKey"),
        "penalty_duration": details.get("duration"),
        "away_score": details.get("awayScore"),
        "home_score": details.get("homeScore"),
        "away_sog": details.get("awaySOG"),
        "home_sog": details.get("homeSOG"),
    }


def _flatten_roster_spot(game_id: int, spot: dict) -> dict:
    return {
        "game_id": game_id,
        "player_id": spot.get("playerId"),
        "team_id": spot.get("teamId"),
        "first_name": (spot.get("firstName") or {}).get("default"),
        "last_name": (spot.get("lastName") or {}).get("default"),
        "sweater_number": spot.get("sweaterNumber"),
        "position_code": spot.get("positionCode"),
    }


# --------------------------------------------------------------------------- #
# Upserts
# --------------------------------------------------------------------------- #

def _upsert(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join(f":{c}" for c in columns)
    col_list = ", ".join(columns)
    conn.executemany(
        f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})",
        rows,
    )


# --------------------------------------------------------------------------- #
# Schedule discovery
# --------------------------------------------------------------------------- #

def discover_games_in_range(client: NHLClient, start_date: str, end_date: str) -> list[dict]:
    """Walk the weekly schedule endpoint across [start_date, end_date] and return raw
    game dicts (as embedded in the schedule payload), deduplicated by game id.

    The NHL API's `nextStartDate` skips empty off-season weeks on its own, so this
    is much cheaper than scanning day by day.
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    if end_dt < start_dt:
        raise ValueError("end_date must be on or after start_date")

    games_by_id: dict[int, dict] = {}
    cursor_dt = start_dt
    visited: set[str] = set()
    total_days = (end_dt - start_dt).days + 1

    # Progress is tracked in calendar days rather than API calls: the NHL API's
    # `nextStartDate` jumps straight over empty off-season weeks, so a single
    # call can advance the cursor by months. Sizing the bar off days keeps it
    # an honest reflection of how far through the date range we are.
    with tqdm(total=total_days, desc="Scanning schedule", unit="day") as bar:
        while cursor_dt.isoformat() not in visited:
            cursor = cursor_dt.isoformat()
            visited.add(cursor)
            payload = _call_with_retry(client.schedule.weekly_schedule, date=cursor)

            for day in payload.get("gameWeek", []):
                for game in day.get("games", []):
                    games_by_id[int(game["id"])] = game

            bar.set_postfix(week_of=cursor, games=len(games_by_id))

            next_start = payload.get("nextStartDate")
            next_dt = datetime.strptime(next_start, "%Y-%m-%d").date() if next_start else None
            if next_dt is None or next_dt > end_dt:
                bar.update(total_days - bar.n)
                break

            bar.update((next_dt - cursor_dt).days)
            cursor_dt = next_dt

    return list(games_by_id.values())


# --------------------------------------------------------------------------- #
# Per-game load
# --------------------------------------------------------------------------- #

def fetch_and_store_game(
    client: NHLClient,
    conn: sqlite3.Connection,
    game_id: int,
    force: bool = False,
) -> bool:
    """Fetch full play-by-play for one game and upsert it into the database.

    Skips games already stored with a final game_state unless `force=True`.
    Returns True if the game was fetched and stored, False if it was skipped.
    """
    game_id = int(game_id)

    if not force:
        row = conn.execute(
            "SELECT game_state FROM games WHERE game_id = ?", (game_id,)
        ).fetchone()
        if row is not None and row[0] in FINAL_GAME_STATES:
            return False

    payload = _call_with_retry(client.game_center.play_by_play, game_id=str(game_id))

    game_row = _flatten_game(payload)
    play_rows = [_flatten_play(game_id, p) for p in payload.get("plays", [])]
    roster_rows = [_flatten_roster_spot(game_id, r) for r in payload.get("rosterSpots", [])]

    with conn:
        _upsert(conn, "games", [game_row])
        conn.execute("DELETE FROM plays WHERE game_id = ?", (game_id,))
        _upsert(conn, "plays", play_rows)
        conn.execute("DELETE FROM roster_spots WHERE game_id = ?", (game_id,))
        _upsert(conn, "roster_spots", roster_rows)

    return True


def load_games(
    client: NHLClient,
    conn: sqlite3.Connection,
    game_ids: Iterable[int],
    force: bool = False,
    desc: str = "Loading play-by-play",
) -> dict:
    """Fetch and store play-by-play for a batch of game ids. Never raises on a
    per-game failure; failures are collected and returned in the summary."""
    game_id_list = list(game_ids)
    loaded, skipped, failed = 0, 0, []

    with tqdm(game_id_list, desc=desc, unit="game") as bar:
        for gid in bar:
            try:
                if fetch_and_store_game(client, conn, gid, force=force):
                    loaded += 1
                else:
                    skipped += 1
            except ResourceNotFoundException:
                failed.append((gid, "not_found"))
            except NHLApiException as exc:
                failed.append((gid, str(exc)))
            bar.set_postfix(game_id=gid, loaded=loaded, skipped=skipped, failed=len(failed))

    return {"loaded": loaded, "skipped": skipped, "failed": failed}


# --------------------------------------------------------------------------- #
# High-level entry points
# --------------------------------------------------------------------------- #

def backfill(
    client: NHLClient,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Path | str = DEFAULT_DB_PATH,
    start_date: str = EARLIEST_SCHEDULE_DATE,
    end_date: Optional[str] = None,
    game_types: Iterable[int] = DEFAULT_GAME_TYPES,
    force: bool = False,
) -> dict:
    """Full historical load: discover every game between start_date and end_date
    (defaults to 2013-09-01 through today) and pull play-by-play for each one
    that has already finished. Safe to re-run - already-loaded games are skipped
    unless `force=True`.
    """
    owns_conn = conn is None
    conn = conn or get_connection(db_path)
    end_date = end_date or date.today().isoformat()
    game_types = set(game_types)

    try:
        raw_games = discover_games_in_range(client, start_date, end_date)
        game_ids = [
            g["id"]
            for g in raw_games
            if g.get("gameType") in game_types and g.get("gameState") in FINAL_GAME_STATES
        ]
        tqdm.write(f"Found {len(game_ids)} finished games between {start_date} and {end_date}.")
        return load_games(client, conn, game_ids, force=force, desc="Backfilling play-by-play")
    finally:
        if owns_conn:
            conn.close()


def update_latest(
    client: NHLClient,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Path | str = DEFAULT_DB_PATH,
    lookback_days: int = 10,
    game_types: Iterable[int] = DEFAULT_GAME_TYPES,
) -> dict:
    """Incremental update: rescan the last `lookback_days` of the schedule and
    (re)load any game that is now final but isn't yet stored as final locally.

    Intended to be run periodically (e.g. daily via cron) to pick up newly
    completed games without redoing the full historical backfill.
    """
    owns_conn = conn is None
    conn = conn or get_connection(db_path)
    game_types = set(game_types)

    try:
        end = date.today()
        start = end - timedelta(days=lookback_days)
        raw_games = discover_games_in_range(client, start.isoformat(), end.isoformat())

        stale_or_missing = []
        for g in raw_games:
            if g.get("gameType") not in game_types:
                continue
            if g.get("gameState") not in FINAL_GAME_STATES:
                continue
            row = conn.execute(
                "SELECT game_state FROM games WHERE game_id = ?", (int(g["id"]),)
            ).fetchone()
            if row is None or row[0] not in FINAL_GAME_STATES:
                stale_or_missing.append(g["id"])

        tqdm.write(
            f"Found {len(stale_or_missing)} new/updated finished games in the last {lookback_days} days."
        )
        return load_games(client, conn, stale_or_missing, desc="Updating recent play-by-play")
    finally:
        if owns_conn:
            conn.close()


# --------------------------------------------------------------------------- #
# Read helpers
# --------------------------------------------------------------------------- #

def read_games(db_path: Path | str = DEFAULT_DB_PATH, where: Optional[str] = None) -> pd.DataFrame:
    """Read the games table into a DataFrame, optionally filtered with a raw SQL WHERE clause."""
    query = "SELECT * FROM games"
    if where:
        query += f" WHERE {where}"
    with get_connection(db_path) as conn:
        return pd.read_sql_query(query, conn)


def read_plays(db_path: Path | str = DEFAULT_DB_PATH, where: Optional[str] = None) -> pd.DataFrame:
    """Read the plays table into a DataFrame, optionally filtered with a raw SQL WHERE clause."""
    query = "SELECT * FROM plays"
    if where:
        query += f" WHERE {where}"
    with get_connection(db_path) as conn:
        return pd.read_sql_query(query, conn)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    sub = parser.add_subparsers(dest="command", required=True)

    p_backfill = sub.add_parser("backfill", help="Full historical load from 2013-14 through today")
    p_backfill.add_argument("--start-date", default=EARLIEST_SCHEDULE_DATE)
    p_backfill.add_argument("--end-date", default=None)
    p_backfill.add_argument("--force", action="store_true")

    p_update = sub.add_parser("update", help="Pull newly completed games")
    p_update.add_argument("--lookback-days", type=int, default=10)

    args = parser.parse_args()
    client = NHLClient()

    if args.command == "backfill":
        summary = backfill(
            client,
            db_path=args.db_path,
            start_date=args.start_date,
            end_date=args.end_date,
            force=args.force,
        )
    else:
        summary = update_latest(client, db_path=args.db_path, lookback_days=args.lookback_days)

    print(summary)


if __name__ == "__main__":
    _main()