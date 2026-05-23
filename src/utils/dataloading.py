from typing import Literal, Optional
from datetime import datetime, timedelta
from pathlib import Path
import os
import tempfile

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
    cols = ['id', 'season', 'gameType', 'venue', 'startTimeUTC', 'awayTeam', 'homeTeam', 'periodDescriptor', 'gameOutcome']
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

# Helper to ensure we can create/append the CSV and fail fast with a clear message
def _ensure_csv_appendable(out_path: Path) -> None:
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # If file exists, test appendability
    if out_path.exists():
        try:
            with open(out_path, "a", newline=""):
                pass
        except PermissionError as e:
            raise PermissionError(
                f"Cannot open '{out_path}' for appending. Close any program (Excel, editor) that has the file open, "
                "or choose a different file_path. Original error: " + str(e)
            ) from e
    else:
        # Test we can create a temporary file in the directory
        try:
            fd, tmp = tempfile.mkstemp(dir=str(out_dir))
            os.close(fd)
            os.remove(tmp)
        except PermissionError as e:
            raise PermissionError(
                f"Cannot create files in directory '{out_dir}'. Check directory permissions or choose a different file_path. "
                "Original error: " + str(e)
            ) from e


def get_games_in_range(
    start_date: str,
    end_date: str,
    client,
    mode: Literal['pandas', 'polars', 'csv'] = 'pandas',
    file_path: Optional[str] = None
) -> None | pd.DataFrame | pl.DataFrame:
    """
    Fetch all games between start_date and end_date (inclusive), show a tqdm progress bar
    and display the last completed date in the bar.

    Modes:
      - 'pandas'  -> returns a pandas.DataFrame
      - 'polars'  -> returns a polars.DataFrame
      - 'csv'     -> appends results to CSV at file_path and returns None

    Dates must be strings in YYYY-MM-DD format.
    When mode == 'csv', file_path must be provided.
    """
    # Validate date format YYYY-MM-DD
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Invalid date format. Please use YYYY-MM-DD.")

    if end_dt < start_dt:
        raise ValueError("end_date must be the same or after start_date")

    # Validate mode
    if mode not in ('pandas', 'polars', 'csv'):
        raise ValueError(f"Unrecognized mode: {mode}")

    # CSV-specific setup
    out_path = None
    csv_existing_ids: set[str] = set()
    csv_created = False
    if mode == 'csv':
        if not file_path:
            raise ValueError("file_path must be provided when mode='csv'")
        out_path = Path(file_path)
        # Ensure directory exists and we can write/append
        _ensure_csv_appendable(out_path)
        # If file exists, read existing ids to avoid duplicates
        if out_path.exists():
            try:
                existing = pd.read_csv(out_path, usecols=['id'])
                csv_existing_ids = set(existing['id'].astype(str).tolist())
                csv_created = True
            except Exception:
                # If reading fails (no id column or other), treat as no existing ids but file exists
                csv_existing_ids = set()
                csv_created = True

    # Build inclusive list of dates
    dates = []
    cur = start_dt
    while cur <= end_dt:
        dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    pandas_frames: list[pd.DataFrame] = []
    polars_frames: list[pl.DataFrame] = []

    # tqdm progress bar: show last completed date via postfix
    with tqdm(dates, desc="Fetching games", unit="day") as bar:
        for d in bar:
            try:
                # For CSV mode, request pandas output so writing is straightforward
                requested_mode = 'pandas' if mode == 'csv' else mode
                daily = get_daily_game_table(date=d, client=client, mode=requested_mode)
            except Exception:
                # update postfix to show last attempted/completed date even on failure
                bar.set_postfix(last_completed=d)
                continue

            # update postfix to show last completed date (successful or empty)
            bar.set_postfix(last_completed=d)

            if daily is None:
                continue

            # CSV mode: write per-day, creating file on first write and appending thereafter
            if mode == 'csv':
                # Normalize to pandas DataFrame
                if isinstance(daily, pl.DataFrame):
                    daily_pd = daily.to_pandas()
                elif isinstance(daily, pd.DataFrame):
                    daily_pd = daily.copy()
                else:
                    # unexpected type, skip
                    continue

                # Ensure id is a column (not index)
                if daily_pd.index.name == 'id' and 'id' not in daily_pd.columns:
                    daily_pd = daily_pd.reset_index()

                # Coerce startTimeUTC if present
                if 'startTimeUTC' in daily_pd.columns:
                    daily_pd['startTimeUTC'] = pd.to_datetime(daily_pd['startTimeUTC'], errors='coerce')

                # Ensure id column exists and compare as strings for dedupe
                if 'id' in daily_pd.columns:
                    daily_pd['id'] = daily_pd['id'].astype(str)
                    new_rows = daily_pd[~daily_pd['id'].isin(csv_existing_ids)]
                else:
                    # If no id column, append everything (can't dedupe)
                    new_rows = daily_pd

                if new_rows.empty:
                    # nothing new to append for this date
                    continue

                # Write/append to CSV safely
                try:
                    write_header = not csv_created
                    # Use mode 'a' to append; header only if file didn't exist
                    new_rows.to_csv(out_path, mode='a', index=False, header=write_header)
                except PermissionError as e:
                    raise PermissionError(
                        f"Failed to write to '{out_path}'. It may be open in another program or you lack write permission. "
                        "Close any program using the file, ensure you have write permission to the directory, "
                        "or pass a different file_path. Original error: " + str(e)
                    ) from e

                # Update tracking state
                if 'id' in new_rows.columns:
                    csv_existing_ids.update(new_rows['id'].astype(str).tolist())
                csv_created = True

            else:
                # Non-CSV modes: collect frames for later concatenation
                if mode == 'pandas':
                    if isinstance(daily, pd.DataFrame):
                        if daily.index.name == 'id' and 'id' not in daily.columns:
                            daily = daily.reset_index()
                        pandas_frames.append(daily)
                    else:
                        continue
                else:  # polars
                    if isinstance(daily, pl.DataFrame):
                        polars_frames.append(daily)
                    else:
                        continue

    # CSV mode writes to disk and returns None
    if mode == 'csv':
        return None

    # No data found
    if mode == 'pandas' and not pandas_frames:
        return None
    if mode == 'polars' and not polars_frames:
        return None

    # Concatenate and deduplicate for pandas
    if mode == 'pandas':
        result = pd.concat(pandas_frames, ignore_index=True, sort=False)
        if 'id' not in result.columns and result.index.name == 'id':
            result = result.reset_index()
        if 'id' in result.columns:
            result = result.drop_duplicates(subset=['id'], keep='first').set_index('id')
        if 'startTimeUTC' in result.columns:
            result['startTimeUTC'] = pd.to_datetime(result['startTimeUTC'], errors='coerce')
        return result

    # Concatenate and deduplicate for polars
    result = pl.concat(polars_frames, how='vertical')
    if 'id' in result.columns:
        result = result.unique(subset=['id'])
    if 'startTimeUTC' in result.columns:
        result = result.with_columns(
            pl.col("startTimeUTC").str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%SZ").alias("startTimeUTC")
        )
    return result