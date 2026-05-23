from typing import Literal, Optional, Iterable
from tqdm.auto import tqdm
import pandas as pd
import polars as pl
from datetime import datetime, timedelta
from nhlpy import NHLClient


def get_daily_game_table(
    date: str,
    client: NHLClient,
    mode: Literal['pandas', 'polars'] = 'pandas'
) -> None | pd.DataFrame | pl.DataFrame:
    """
    Fetch the daily games for `date` and return a flattened table.
    Returns None when no games are present for the date.
    """
    payload = client.schedule.daily_schedule(date=date)
    games = payload.get('games') if isinstance(payload, dict) else None

    if not games:
        return None

    cols = [
        'id', 'season', 'gameType', 'venue', 'startTimeUTC',
        'awayTeam', 'homeTeam', 'periodDescriptor', 'gameOutcome'
    ]
    games_cleaned = [{k: v for k, v in game.items() if k in cols} for game in games]

    if mode == 'pandas':
        result = pd.json_normalize(games_cleaned, sep='_')
        if 'startTimeUTC' in result.columns:
            result['startTimeUTC'] = pd.to_datetime(result['startTimeUTC'], errors='coerce')
        # keep id as a column for downstream union/concat logic
        if result.index.name == 'id' and 'id' not in result.columns:
            result = result.reset_index()
        return result

    elif mode == 'polars':
        result = pl.json_normalize(games_cleaned, separator='_')
        if 'startTimeUTC' in result.columns:
            result = result.with_columns(
                pl.col("startTimeUTC").str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%SZ").alias("startTimeUTC")
            )
        return result

    else:
        raise ValueError(f"Unrecognized mode: {mode}")


def get_games_in_range(
    start_date: str,
    end_date: str,
    client: NHLClient,
    mode: Literal['pandas', 'polars'] = 'pandas'
) -> None | pd.DataFrame | pl.DataFrame:
    """
    Fetch all games between start_date and end_date (inclusive), show a tqdm progress bar
    and display the last completed date in the bar.

    - mode 'pandas' returns a pandas.DataFrame
    - mode 'polars' returns a polars.DataFrame

    Dates must be strings in YYYY-MM-DD format.
    """
    # Validate date format YYYY-MM-DD
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Invalid date format. Please use YYYY-MM-DD.")

    if end_dt < start_dt:
        raise ValueError("end_date must be the same or after start_date")

    if mode not in ('pandas', 'polars'):
        raise ValueError(f"Unrecognized mode: {mode}")

    # Build inclusive list of dates
    dates: list[str] = []
    cur = start_dt
    while cur <= end_dt:
        dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    pandas_frames: list[pd.DataFrame] = []

    # Use pandas as the canonical per-day format to ensure union of columns across days.
    with tqdm(dates, desc="Fetching games", unit="day") as bar:
        for d in bar:
            try:
                # Always request pandas from the daily function to get consistent, unionable frames
                daily = get_daily_game_table(date=d, client=client, mode='pandas')
            except Exception:
                # update postfix to show last attempted/completed date even on failure
                bar.set_postfix(last_completed=d)
                continue

            # update postfix to show last completed date (successful or empty)
            bar.set_postfix(last_completed=d)

            if daily is None:
                continue

            # Ensure id is a column (not index)
            if isinstance(daily, pd.DataFrame):
                if daily.index.name == 'id' and 'id' not in daily.columns:
                    daily = daily.reset_index()
                pandas_frames.append(daily)
            else:
                # unexpected type returned; skip
                continue

    # No data found
    if not pandas_frames:
        return None

    # Concatenate with union of columns (columns present in any daily frame will be included)
    result_pd = pd.concat(pandas_frames, ignore_index=True, sort=False)

    # Ensure id is a column; if it's the index, reset it
    if 'id' not in result_pd.columns and result_pd.index.name == 'id':
        result_pd = result_pd.reset_index()

    # Remove duplicates by id if present, keep first occurrence
    if 'id' in result_pd.columns:
        # keep id as column for now; set index later for pandas mode
        result_pd = result_pd.drop_duplicates(subset=['id'], keep='first')

    # Ensure startTimeUTC is datetime if present
    if 'startTimeUTC' in result_pd.columns:
        result_pd['startTimeUTC'] = pd.to_datetime(result_pd['startTimeUTC'], errors='coerce')

    if mode == 'pandas':
        # set id as index for pandas return if available
        if 'id' in result_pd.columns:
            result_pd = result_pd.set_index('id')
        return result_pd

    # mode == 'polars': convert pandas result to polars, preserving all columns
    # Reset index so 'id' is a column if it was the index
    if result_pd.index.name == 'id':
        result_pd = result_pd.reset_index()

    # Convert to polars; polars will infer dtypes. Parse startTimeUTC explicitly if present.
    result_pl = pl.from_pandas(result_pd)

    if 'startTimeUTC' in result_pl.columns:
        result_pl = result_pl.with_columns(
            pl.col("startTimeUTC").str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%SZ").alias("startTimeUTC")
        )

    # Deduplicate in polars by id if present
    if 'id' in result_pl.columns:
        result_pl = result_pl.unique(subset=['id'])

    return result_pl

def _detect_event_id_column(df: pd.DataFrame) -> Optional[str]:
    """Return the best column name to use as a unique play id, or None."""
    candidates = [
        "about_eventId", "eventId", "about_eventIdx", "eventIdx",
        "playIndex", "id"
    ]
    for c in candidates:
        if c in df.columns:
            return c
    return None

def get_pbp_for_games(
    game_ids: Iterable[str],
    client: NHLClient,
    mode: Literal['pandas', 'polars'] = 'pandas'
) -> None | pd.DataFrame | pl.DataFrame:
    """
    Fetch play-by-play for each game_id in game_ids and return a single table.

    - game_ids: iterable of game id strings (e.g., ['2013020004', ...])
    - client: NHLClient instance
    - mode: 'pandas' or 'polars' (default 'pandas')

    Behavior:
    - Normalizes nested play JSON with pd.json_normalize(..., sep='_').
    - Keeps the union of columns across all games.
    - Adds a canonical 'game_id' column and a canonical 'eventId' column (created if missing).
    - Deduplicates plays using the composite key (game_id, eventId).
    - Returns None if no plays were found for any game.
    """
    if mode not in ("pandas", "polars"):
        raise ValueError("mode must be 'pandas' or 'polars'")

    per_game_frames: list[pd.DataFrame] = []
    any_plays = False

    game_list = list(game_ids)
    with tqdm(game_list, desc="Fetching PBP", unit="game") as bar:
        for gid in bar:
            try:
                payload = client.game_center.play_by_play(game_id=str(gid))
            except Exception:
                bar.set_postfix(last_completed=gid)
                continue

            bar.set_postfix(last_completed=gid)

            plays = payload.get("plays") if isinstance(payload, dict) else None
            if not plays:
                continue

            try:
                df = pd.json_normalize(plays, sep="_")
            except Exception:
                continue

            # Attach game_id for every row
            df["game_id"] = str(gid)

            # Detect an event id column; if missing, create a synthetic one
            event_col = _detect_event_id_column(df)
            if event_col is None:
                # synthetic per-play id using game id + row index
                df["__row_id"] = df.index.to_series().apply(lambda i, g=gid: f"{g}_{i}")
                event_col = "__row_id"

            # Create a canonical 'eventId' column (string) for dedupe across games
            df["eventId"] = df[event_col].astype(str)

            # Ensure game_id is string for robust dedupe
            df["game_id"] = df["game_id"].astype(str)

            # Record which column was used (optional, kept in attrs)
            df.attrs["event_id_col"] = event_col

            per_game_frames.append(df)
            any_plays = True

    if not any_plays:
        return None

    # Build canonical union of columns across all frames
    all_columns: list[str] = []
    for f in per_game_frames:
        for c in f.columns:
            if c not in all_columns:
                all_columns.append(c)

    # Ensure canonical columns include 'game_id' and 'eventId' (they should)
    if "game_id" not in all_columns:
        all_columns.insert(0, "game_id")
    if "eventId" not in all_columns:
        all_columns.insert(1 if all_columns[0] == "game_id" else 0, "eventId")

    # Reindex each frame to the canonical column order (adds missing cols as NaN)
    reindexed_frames = [f.reindex(columns=all_columns) for f in per_game_frames]

    # Concatenate (union of columns preserved)
    combined = pd.concat(reindexed_frames, ignore_index=True, sort=False)

    # Ensure game_id and eventId exist and are strings
    if "game_id" not in combined.columns:
        combined["game_id"] = combined.index.to_series().apply(lambda i: "")
    combined["game_id"] = combined["game_id"].astype(str)

    if "eventId" not in combined.columns:
        combined["eventId"] = combined.index.to_series().apply(lambda i: f"{i}")
    combined["eventId"] = combined["eventId"].astype(str)

    # Deduplicate by composite key (game_id, eventId), keep first occurrence
    combined = combined.drop_duplicates(subset=["game_id", "eventId"], keep="first").reset_index(drop=True)

    # Parse common datetime fields if present
    if "about_dateTime" in combined.columns:
        combined["about_dateTime"] = pd.to_datetime(combined["about_dateTime"], errors="coerce")
    elif "dateTime" in combined.columns:
        combined["dateTime"] = pd.to_datetime(combined["dateTime"], errors="coerce")

    if mode == "pandas":
        return combined

    # polars: convert from pandas to polars, then coerce datetime if needed
    result_pl = pl.from_pandas(combined)

    # Parse datetimes in polars if present (attempt common formats)
    if "about_dateTime" in result_pl.columns:
        # try timezone-aware then fallback to naive if parsing fails
        try:
            result_pl = result_pl.with_columns(
                pl.col("about_dateTime").str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S%z").alias("about_dateTime")
            )
        except Exception:
            result_pl = result_pl.with_columns(
                pl.col("about_dateTime").str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S").alias("about_dateTime")
            )
    elif "dateTime" in result_pl.columns:
        try:
            result_pl = result_pl.with_columns(
                pl.col("dateTime").str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S%z").alias("dateTime")
            )
        except Exception:
            result_pl = result_pl.with_columns(
                pl.col("dateTime").str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S").alias("dateTime")
            )

    # Deduplicate in polars by composite key if both columns exist
    if all(c in result_pl.columns for c in ["game_id", "eventId"]):
        result_pl = result_pl.unique(subset=["game_id", "eventId"])

    return result_pl