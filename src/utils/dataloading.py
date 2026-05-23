from typing import Literal, Optional
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import polars as pl
from tqdm.auto import tqdm
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