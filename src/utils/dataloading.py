from typing import Literal
from datetime import datetime, timedelta
import pandas as pd
import polars as pl
from tqdm.auto import tqdm
from nhlpy import NHLClient

def get_daily_game_table(
        date: str,
        client: NHLClient,
        mode: Literal['pandas', 'polars'] = 'pandas'
    ) -> None|pd.DataFrame|pl.DataFrame:
        
    games = client.schedule.daily_schedule(date=date)['games']
    games_cleaned = [{k:v for k,v in game.items() if k in cols} for game in games]

    if mode == 'pandas' or mode == 'csv':
        result = pd.json_normalize(games_cleaned, sep='_')
        result['startTimeUTC'] = pd.to_datetime(result.startTimeUTC)
        result = result.set_index('id')
    elif mode == 'polars':
        result = pl.json_normalize(games_cleaned, separator='_')
        result = result.with_columns(
            pl.col("startTimeUTC").str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%SZ").alias("startTimeUTC")
        )
    else:
        raise ValueError(f'Unrecognized mode: {mode}')

    return result

def get_games_in_range(
    start_date: str,
    end_date: str,
    client: NHLClient,
    mode: Literal['pandas', 'polars'] = 'pandas'
) -> None | pd.DataFrame | pl.DataFrame:
    """
    Fetch all games between start_date and end_date (inclusive), show a tqdm progress bar
    and display the last completed date in the bar. Dates must be 'YYYY-MM-DD'.
    """
    # Validate date format YYYY-MM-DD
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Invalid date format. Please use YYYY-MM-DD.")

    if end_dt < start_dt:
        raise ValueError("end_date must be the same or after start_date")

    # Normalize mode
    if mode == 'csv':
        mode = 'pandas'
    if mode not in ('pandas', 'polars'):
        raise ValueError(f"Unrecognized mode: {mode}")

    # Build inclusive list of dates
    dates = []
    cur = start_dt
    while cur <= end_dt:
        dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    pandas_frames = []
    polars_frames = []

    # tqdm progress bar: show last completed date via postfix
    with tqdm(dates, desc="Fetching games", unit="day") as bar:
        for d in bar:
            # fetch daily; get_daily_game_table returns None for empty days
            try:
                daily = get_daily_game_table(date=d, client=client, mode=mode)
            except Exception:
                # still update bar to show this date as completed (failed)
                bar.set_postfix(last_completed=d)
                continue

            # update postfix to show last completed date (successful or empty)
            bar.set_postfix(last_completed=d)

            if daily is None:
                continue

            if mode == 'pandas':
                if isinstance(daily, pd.DataFrame):
                    if daily.index.name == 'id' and 'id' not in daily.columns:
                        daily = daily.reset_index()
                    pandas_frames.append(daily)
                else:
                    # unexpected type, skip
                    continue
            else:  # polars
                if isinstance(daily, pl.DataFrame):
                    polars_frames.append(daily)
                else:
                    continue

    # No data found
    if mode == 'pandas' and not pandas_frames:
        return None
    if mode == 'polars' and not polars_frames:
        return None

    # Concatenate and deduplicate
    if mode == 'pandas':
        result = pd.concat(pandas_frames, ignore_index=True, sort=False)
        if 'id' not in result.columns and result.index.name == 'id':
            result = result.reset_index()
        if 'id' in result.columns:
            result = result.drop_duplicates(subset=['id'], keep='first').set_index('id')
        if 'startTimeUTC' in result.columns:
            result['startTimeUTC'] = pd.to_datetime(result['startTimeUTC'], errors='coerce')
        return result

    else:  # polars
        result = pl.concat(polars_frames, how='vertical')
        if 'id' in result.columns:
            result = result.unique(subset=['id'])
        if 'startTimeUTC' in result.columns:
            result = result.with_columns(
                pl.col("startTimeUTC").str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%SZ").alias("startTimeUTC")
            )
        return result
