"""Postgres connection, schema, and bulk-write helpers.

Every table is keyed so that re-running a load is idempotent: dimension /
snapshot tables use ``INSERT ... ON CONFLICT DO UPDATE`` (`upsert_rows`),
and the two high-volume per-game tables (`playbyplay`, `game_rosters`) are
loaded with delete-then-``COPY`` per game (`replace_rows_for_games`), which
is both correct (a game's plays can legitimately change until it goes
final) and fast at the row volumes involved.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import psycopg

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    team_id            INTEGER PRIMARY KEY,
    abbrev             TEXT NOT NULL,
    common_name        TEXT,
    place_name         TEXT,
    updated_at         TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS schedules (
    game_id             BIGINT PRIMARY KEY,
    season              INTEGER NOT NULL,
    game_type           SMALLINT NOT NULL,
    game_date           DATE NOT NULL,
    start_time_utc      TIMESTAMPTZ,
    venue               TEXT,
    venue_timezone      TEXT,
    neutral_site        BOOLEAN,
    away_team_id        INTEGER,
    away_team_abbrev    TEXT,
    home_team_id        INTEGER,
    home_team_abbrev    TEXT,
    game_state          TEXT,
    game_schedule_state TEXT,
    tv_broadcasts       JSONB,
    updated_at          TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schedules_season ON schedules (season);
CREATE INDEX IF NOT EXISTS idx_schedules_date ON schedules (game_date);

CREATE TABLE IF NOT EXISTS games (
    game_id             BIGINT PRIMARY KEY,
    season              INTEGER NOT NULL,
    game_type           SMALLINT NOT NULL,
    game_date           DATE NOT NULL,
    venue               TEXT,
    away_team_id        INTEGER,
    away_team_abbrev    TEXT,
    away_score          SMALLINT,
    home_team_id        INTEGER,
    home_team_abbrev    TEXT,
    home_score          SMALLINT,
    game_state          TEXT NOT NULL,
    game_schedule_state TEXT,
    periods_played      SMALLINT,
    final_period_type   TEXT,
    winning_goalie_id   INTEGER,
    winning_goal_scorer_id INTEGER,
    updated_at          TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_games_season ON games (season);
CREATE INDEX IF NOT EXISTS idx_games_date ON games (game_date);

CREATE TABLE IF NOT EXISTS standings (
    standings_date      DATE NOT NULL,
    team_abbrev         TEXT NOT NULL,
    season              INTEGER,
    game_type_id        SMALLINT,
    team_name           TEXT,
    team_common_name    TEXT,
    conference_abbrev   TEXT,
    division_abbrev     TEXT,
    games_played        SMALLINT,
    wins                SMALLINT,
    losses              SMALLINT,
    ot_losses           SMALLINT,
    ties                SMALLINT,
    points              SMALLINT,
    point_pctg          REAL,
    regulation_wins     SMALLINT,
    regulation_plus_ot_wins SMALLINT,
    goal_for            SMALLINT,
    goal_against        SMALLINT,
    goal_differential   SMALLINT,
    streak_code         TEXT,
    streak_count        SMALLINT,
    league_sequence     SMALLINT,
    conference_sequence SMALLINT,
    division_sequence   SMALLINT,
    wildcard_sequence   SMALLINT,
    updated_at          TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (standings_date, team_abbrev)
);
CREATE INDEX IF NOT EXISTS idx_standings_season ON standings (season);

CREATE TABLE IF NOT EXISTS rosters (
    season                INTEGER NOT NULL,
    team_abbrev           TEXT NOT NULL,
    player_id             INTEGER NOT NULL,
    first_name            TEXT,
    last_name             TEXT,
    sweater_number        SMALLINT,
    position_code         TEXT,
    position_group        TEXT,
    shoots_catches        TEXT,
    height_in_inches      SMALLINT,
    weight_in_pounds      SMALLINT,
    birth_date            DATE,
    birth_city            TEXT,
    birth_country         TEXT,
    birth_state_province  TEXT,
    updated_at             TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (season, team_abbrev, player_id)
);
CREATE INDEX IF NOT EXISTS idx_rosters_player ON rosters (player_id);

CREATE TABLE IF NOT EXISTS players (
    player_id             INTEGER PRIMARY KEY,
    first_name            TEXT,
    last_name             TEXT,
    position              TEXT,
    is_active              BOOLEAN,
    current_team_abbrev    TEXT,
    sweater_number          SMALLINT,
    height_in_inches        SMALLINT,
    weight_in_pounds        SMALLINT,
    birth_date               DATE,
    birth_city                TEXT,
    birth_country              TEXT,
    birth_state_province        TEXT,
    shoots_catches                TEXT,
    draft_year                     SMALLINT,
    draft_round                     SMALLINT,
    draft_overall                    SMALLINT,
    draft_team_abbrev                 TEXT,
    updated_at                         TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS playbyplay (
    game_id                 BIGINT NOT NULL,
    event_id                INTEGER NOT NULL,
    sort_order               INTEGER,
    period                   SMALLINT,
    period_type              TEXT,
    time_in_period           TEXT,
    time_remaining           TEXT,
    situation_code           TEXT,
    home_team_defending_side TEXT,
    type_code                SMALLINT,
    type_desc_key            TEXT,
    x_coord                  REAL,
    y_coord                  REAL,
    zone_code                TEXT,
    event_owner_team_id      INTEGER,
    shot_type                TEXT,
    reason                   TEXT,
    secondary_reason         TEXT,
    scoring_player_id        INTEGER,
    scoring_player_total     SMALLINT,
    assist1_player_id        INTEGER,
    assist1_player_total     SMALLINT,
    assist2_player_id        INTEGER,
    assist2_player_total     SMALLINT,
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
    penalty_duration         SMALLINT,
    away_score               SMALLINT,
    home_score               SMALLINT,
    away_sog                 SMALLINT,
    home_sog                 SMALLINT,
    PRIMARY KEY (game_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_playbyplay_type ON playbyplay (type_desc_key);
CREATE INDEX IF NOT EXISTS idx_playbyplay_scoring_player ON playbyplay (scoring_player_id);

CREATE TABLE IF NOT EXISTS game_rosters (
    game_id        BIGINT NOT NULL,
    player_id      INTEGER NOT NULL,
    team_id        INTEGER,
    first_name     TEXT,
    last_name      TEXT,
    sweater_number SMALLINT,
    position_code  TEXT,
    PRIMARY KEY (game_id, player_id)
);
CREATE INDEX IF NOT EXISTS idx_game_rosters_player ON game_rosters (player_id);
"""


def connect(
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str,
) -> psycopg.Connection:
    conn = psycopg.connect(
        host=host, port=port, dbname=dbname, user=user, password=password, autocommit=False
    )
    return conn


def create_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()


def upsert_rows(
    conn: psycopg.Connection,
    table: str,
    rows: Sequence[dict],
    conflict_cols: Sequence[str],
    batch_size: int = 2000,
) -> int:
    """INSERT ... ON CONFLICT (conflict_cols) DO UPDATE for every row.

    All rows must share the same set of keys (the first row's keys are taken
    as the column list). Returns the number of rows written.
    """
    if not rows:
        return 0

    columns = list(rows[0].keys())
    update_cols = [c for c in columns if c not in conflict_cols]

    col_list = ", ".join(columns)
    placeholders = ", ".join(f"%({c})s" for c in columns)
    conflict_list = ", ".join(conflict_cols)

    if update_cols:
        update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        stmt = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_list}) DO UPDATE SET {update_clause}"
        )
    else:
        stmt = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_list}) DO NOTHING"
        )

    with conn.cursor() as cur:
        for i in range(0, len(rows), batch_size):
            cur.executemany(stmt, rows[i : i + batch_size])
    conn.commit()
    return len(rows)


def replace_rows_for_games(
    conn: psycopg.Connection,
    table: str,
    columns: Sequence[str],
    rows_by_game: dict[int, list[dict]],
) -> int:
    """Delete any existing rows for each game_id in `rows_by_game`, then COPY in the
    fresh rows. Used for playbyplay/game_rosters, where a game's rows are only
    meaningful as a complete replacement of everything previously stored for it.
    """
    game_ids = list(rows_by_game.keys())
    if not game_ids:
        return 0

    total = 0
    col_list = ", ".join(columns)
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {table} WHERE game_id = ANY(%s)", (game_ids,))
        with cur.copy(f"COPY {table} ({col_list}) FROM STDIN") as copy:
            for game_id in game_ids:
                for row in rows_by_game[game_id]:
                    copy.write_row([row.get(c) for c in columns])
                    total += 1
    conn.commit()
    return total


def existing_ids(conn: psycopg.Connection, query: str, params: Iterable = ()) -> set:
    with conn.cursor() as cur:
        cur.execute(query, tuple(params))
        return {row[0] for row in cur.fetchall()}
