"""Orchestration: turns NHL API calls + flatteners + db writes into the handful of
sync steps that `backfill` and `update` compose.
"""

from __future__ import annotations

from datetime import date, timedelta

from nhlpy import NHLClient
from nhlpy.http_client import NHLApiException, ResourceNotFoundException
from tqdm.auto import tqdm

from . import db, flatten, seasons
from .constants import FINAL_GAME_STATES, ROSTER_POSITION_GROUPS
from .nhl_client import call_with_retry

PLAY_COLUMNS = [
    "game_id", "event_id", "sort_order", "period", "period_type", "time_in_period",
    "time_remaining", "situation_code", "home_team_defending_side", "type_code",
    "type_desc_key", "x_coord", "y_coord", "zone_code", "event_owner_team_id",
    "shot_type", "reason", "secondary_reason", "scoring_player_id", "scoring_player_total",
    "assist1_player_id", "assist1_player_total", "assist2_player_id", "assist2_player_total",
    "goalie_in_net_id", "shooting_player_id", "blocking_player_id", "hitting_player_id",
    "hittee_player_id", "winning_player_id", "losing_player_id", "player_id",
    "committed_by_player_id", "drawn_by_player_id", "served_by_player_id",
    "penalty_severity", "penalty_desc_key", "penalty_duration", "away_score",
    "home_score", "away_sog", "home_sog",
]

ROSTER_SPOT_COLUMNS = [
    "game_id", "player_id", "team_id", "first_name", "last_name", "sweater_number", "position_code",
]


# --------------------------------------------------------------------------- #
# schedules / games / standings / teams
# --------------------------------------------------------------------------- #

def sync_schedule(client: NHLClient, conn, start_date: str, end_date: str) -> dict:
    """Walk the weekly schedule endpoint over [start_date, end_date], pulling a
    standings snapshot at each visited week, and upsert schedules / games / teams
    / standings. Mirrors the NHL API's own week-skipping behaviour (`nextStartDate`
    jumps straight over empty off-season weeks), so this is cheap even for
    multi-year ranges.
    """
    start_dt = date.fromisoformat(start_date)
    end_dt = date.fromisoformat(end_date)
    if end_dt < start_dt:
        raise ValueError("end_date must be on or after start_date")

    schedule_rows: dict[int, dict] = {}
    game_rows: dict[int, dict] = {}
    team_rows: dict[int, dict] = {}
    standings_rows: list[dict] = []

    cursor_dt = start_dt
    visited: set[str] = set()
    total_days = (end_dt - start_dt).days + 1

    with tqdm(total=total_days, desc="Scanning schedule + standings", unit="day") as bar:
        while cursor_dt.isoformat() not in visited:
            cursor = cursor_dt.isoformat()
            visited.add(cursor)

            payload = call_with_retry(client.schedule.weekly_schedule, date=cursor)
            for day in payload.get("gameWeek", []):
                day_date = day.get("date")
                for game in day.get("games", []):
                    game_id = int(game["id"])
                    schedule_rows[game_id] = flatten.flatten_schedule_game(game, day_date)
                    if game.get("gameState") in FINAL_GAME_STATES:
                        game_rows[game_id] = flatten.flatten_game_result(game, day_date)
                    for team_row in flatten.flatten_teams_from_schedule_game(game):
                        team_rows[team_row["team_id"]] = team_row

            try:
                standings_payload = call_with_retry(client.standings.league_standings, date=cursor)
                for entry in standings_payload.get("standings", []):
                    standings_rows.append(flatten.flatten_standings_entry(entry))
            except NHLApiException:
                pass  # no standings for this date (e.g. deep off-season) - not fatal

            bar.set_postfix(week_of=cursor, games=len(schedule_rows))

            next_start = payload.get("nextStartDate")
            next_dt = date.fromisoformat(next_start) if next_start else None
            if next_dt is None or next_dt > end_dt:
                bar.update(total_days - bar.n)
                break
            bar.update((next_dt - cursor_dt).days)
            cursor_dt = next_dt

    if team_rows:
        db.upsert_rows(conn, "teams", list(team_rows.values()), conflict_cols=["team_id"])
    if schedule_rows:
        db.upsert_rows(conn, "schedules", list(schedule_rows.values()), conflict_cols=["game_id"])
    if game_rows:
        db.upsert_rows(conn, "games", list(game_rows.values()), conflict_cols=["game_id"])
    if standings_rows:
        db.upsert_rows(conn, "standings", standings_rows, conflict_cols=["standings_date", "team_abbrev"])

    return {
        "scheduled_games": len(schedule_rows),
        "completed_games": len(game_rows),
        "standings_rows": len(standings_rows),
        "teams": len(team_rows),
    }


# --------------------------------------------------------------------------- #
# rosters (season-level team roster)
# --------------------------------------------------------------------------- #

def discover_season_team_abbrevs(conn, season_ints: list[int]) -> dict[int, set[str]]:
    """Every (season, team_abbrev) pair already present in `schedules` - used to
    know which teams to pull season rosters for, without hard-coding team lists
    that go stale as franchises are added/relocated/renamed.
    """
    query = """
        SELECT season, team_abbrev FROM (
            SELECT season, home_team_abbrev AS team_abbrev FROM schedules WHERE season = ANY(%s)
            UNION
            SELECT season, away_team_abbrev AS team_abbrev FROM schedules WHERE season = ANY(%s)
        ) t
        WHERE team_abbrev IS NOT NULL
    """
    result: dict[int, set[str]] = {s: set() for s in season_ints}
    with conn.cursor() as cur:
        cur.execute(query, (season_ints, season_ints))
        for season, abbrev in cur.fetchall():
            result.setdefault(season, set()).add(abbrev)
    return result


def sync_rosters(client: NHLClient, conn, team_abbrevs_by_season: dict[int, set[str]]) -> dict:
    pairs = [
        (season, abbrev)
        for season, abbrevs in sorted(team_abbrevs_by_season.items())
        for abbrev in sorted(abbrevs)
    ]
    rows: list[dict] = []
    failed: list[tuple[int, str]] = []

    with tqdm(pairs, desc="Loading team rosters", unit="team-season") as bar:
        for season, abbrev in bar:
            bar.set_postfix(season=seasons.format_season(season), team=abbrev)
            try:
                payload = call_with_retry(client.teams.team_roster, team_abbr=abbrev, season=str(season))
            except ResourceNotFoundException:
                failed.append((season, abbrev))
                continue
            for group in ROSTER_POSITION_GROUPS:
                for player in payload.get(group, []):
                    rows.append(flatten.flatten_roster_player(season, abbrev, player, group))

    if rows:
        db.upsert_rows(conn, "rosters", rows, conflict_cols=["season", "team_abbrev", "player_id"])

    return {"rows": len(rows), "team_seasons": len(pairs), "failed": failed}


# --------------------------------------------------------------------------- #
# playbyplay / game_rosters (per-game)
# --------------------------------------------------------------------------- #

def sync_playbyplay(
    client: NHLClient,
    conn,
    season_ints: list[int],
    force: bool = False,
    flush_every: int = 50,
) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT game_id FROM games WHERE season = ANY(%s) AND game_state = ANY(%s)",
            (season_ints, list(FINAL_GAME_STATES)),
        )
        candidates = {row[0] for row in cur.fetchall()}

    if force:
        game_ids = sorted(candidates)
        skipped = 0
    else:
        loaded_ids = db.existing_ids(conn, "SELECT DISTINCT game_id FROM playbyplay")
        game_ids = sorted(candidates - loaded_ids)
        skipped = len(candidates) - len(game_ids)

    loaded = 0
    failed: list[int] = []
    play_buffer: dict[int, list[dict]] = {}
    roster_buffer: dict[int, list[dict]] = {}

    def flush() -> None:
        if play_buffer:
            db.replace_rows_for_games(conn, "playbyplay", PLAY_COLUMNS, dict(play_buffer))
        if roster_buffer:
            db.replace_rows_for_games(conn, "game_rosters", ROSTER_SPOT_COLUMNS, dict(roster_buffer))
        play_buffer.clear()
        roster_buffer.clear()

    with tqdm(game_ids, desc="Loading play-by-play", unit="game") as bar:
        for i, game_id in enumerate(bar):
            try:
                payload = call_with_retry(client.game_center.play_by_play, game_id=str(game_id))
            except ResourceNotFoundException:
                failed.append(game_id)
                continue
            except NHLApiException:
                failed.append(game_id)
                continue

            play_buffer[game_id] = [flatten.flatten_play(game_id, p) for p in payload.get("plays", [])]
            roster_buffer[game_id] = [
                flatten.flatten_roster_spot(game_id, r) for r in payload.get("rosterSpots", [])
            ]
            loaded += 1

            if (i + 1) % flush_every == 0:
                flush()
            bar.set_postfix(loaded=loaded, skipped=skipped, failed=len(failed))

    flush()
    return {"loaded": loaded, "skipped": skipped, "failed": failed}


# --------------------------------------------------------------------------- #
# players (bio dimension)
# --------------------------------------------------------------------------- #

def discover_missing_player_ids(conn) -> list[int]:
    query = """
        SELECT player_id FROM rosters
        UNION
        SELECT player_id FROM game_rosters
        EXCEPT
        SELECT player_id FROM players
    """
    with conn.cursor() as cur:
        cur.execute(query)
        return [row[0] for row in cur.fetchall() if row[0] is not None]


def sync_players(client: NHLClient, conn, flush_every: int = 200) -> dict:
    player_ids = discover_missing_player_ids(conn)
    rows: list[dict] = []
    failed: list[int] = []

    with tqdm(player_ids, desc="Loading player bios", unit="player") as bar:
        for i, player_id in enumerate(bar):
            try:
                payload = call_with_retry(client.stats.player_career_stats, player_id=str(player_id))
            except ResourceNotFoundException:
                failed.append(player_id)
                continue
            except NHLApiException:
                failed.append(player_id)
                continue

            rows.append(flatten.flatten_player_bio(payload))
            if (i + 1) % flush_every == 0 and rows:
                db.upsert_rows(conn, "players", rows, conflict_cols=["player_id"])
                rows = []
            bar.set_postfix(loaded=i + 1 - len(failed), failed=len(failed))

    if rows:
        db.upsert_rows(conn, "players", rows, conflict_cols=["player_id"])

    return {"loaded": len(player_ids) - len(failed), "failed": failed}


# --------------------------------------------------------------------------- #
# High-level entry points
# --------------------------------------------------------------------------- #

def run_backfill(
    client: NHLClient,
    conn,
    start_season: str,
    end_season: str,
    skip_playbyplay: bool = False,
    skip_players: bool = False,
    force_playbyplay: bool = False,
) -> dict:
    """Full historical load: schedule/standings for every season in range, season
    rosters for every team that played in one, play-by-play for every completed
    game, and bios for every player discovered along the way. Safe to re-run -
    already-loaded games/players are skipped unless forced.
    """
    season_ints = seasons.season_range(start_season, end_season)
    start_date = seasons.season_date_bounds(min(season_ints))[0]
    end_date = min(date.today().isoformat(), seasons.season_date_bounds(max(season_ints))[1])

    tqdm.write(
        f"Backfilling {seasons.format_season(min(season_ints))} through "
        f"{seasons.format_season(max(season_ints))} ({start_date} to {end_date})"
    )

    summary: dict = {"schedule": sync_schedule(client, conn, start_date, end_date)}

    team_abbrevs_by_season = discover_season_team_abbrevs(conn, season_ints)
    summary["rosters"] = sync_rosters(client, conn, team_abbrevs_by_season)

    if not skip_playbyplay:
        summary["playbyplay"] = sync_playbyplay(client, conn, season_ints, force=force_playbyplay)

    if not skip_players:
        summary["players"] = sync_players(client, conn)

    return summary


def run_update(
    client: NHLClient,
    conn,
    lookback_days: int | None = None,
    overlap_days: int = 3,
    skip_players: bool = False,
) -> dict:
    """Incremental update: fills in the most recent games/weeks. By default, picks
    up right where the database left off (the latest `game_date` already stored,
    minus a small overlap to catch late corrections) through today. Pass
    `lookback_days` to instead rescan a fixed trailing window regardless of what's
    already loaded.
    """
    end_date = date.today()

    if lookback_days is not None:
        start_date = end_date - timedelta(days=lookback_days)
    else:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(game_date) FROM schedules")
            (latest,) = cur.fetchone()
        if latest is None:
            raise RuntimeError(
                "No existing data found in `schedules` - run `backfill` first, "
                "or pass --lookback-days to scan a specific trailing window."
            )
        start_date = latest - timedelta(days=overlap_days)

    start_date_str, end_date_str = start_date.isoformat(), end_date.isoformat()
    tqdm.write(f"Updating from {start_date_str} through {end_date_str}")

    summary: dict = {"schedule": sync_schedule(client, conn, start_date_str, end_date_str)}

    season_ints = sorted(
        {seasons.containing_season(start_date_str), seasons.containing_season(end_date_str)}
    )
    team_abbrevs_by_season = discover_season_team_abbrevs(conn, season_ints)
    summary["rosters"] = sync_rosters(client, conn, team_abbrevs_by_season)
    summary["playbyplay"] = sync_playbyplay(client, conn, season_ints, force=False)

    if not skip_players:
        summary["players"] = sync_players(client, conn)

    return summary
