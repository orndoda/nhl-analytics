"""Helpers for converting between human season strings ("2013-2014") and the
NHL API's season identifiers (20132014), and for bounding a season in time.
"""

from __future__ import annotations

from datetime import date

# First regular-season/preseason games of the 2013-14 campaign start in mid-September 2013.
EARLIEST_SEASON = "2013-2014"


def parse_season(season: str | int) -> int:
    """Normalize a season into the NHL API's YYYYYYYY integer form.

    Accepts "2013-2014", "2013" (implying 2013-2014), or 20132014 / "20132014".
    """
    s = str(season).strip()

    if "-" in s:
        start_str, end_str = s.split("-", 1)
        start_year, end_year = int(start_str), int(end_str)
    elif len(s) == 8:
        start_year, end_year = int(s[:4]), int(s[4:])
    elif len(s) == 4:
        start_year, end_year = int(s), int(s) + 1
    else:
        raise ValueError(f"Unrecognized season format: {season!r}")

    if end_year != start_year + 1:
        raise ValueError(f"Season years must be consecutive, got {season!r}")

    return int(f"{start_year}{end_year}")


def format_season(season: int) -> str:
    """20132014 -> '2013-2014'."""
    s = str(season)
    if len(s) != 8:
        raise ValueError(f"Not a valid NHL season id: {season!r}")
    return f"{s[:4]}-{s[4:]}"


def season_years(season: int) -> tuple[int, int]:
    """20132014 -> (2013, 2014)."""
    s = str(season)
    return int(s[:4]), int(s[4:])


def season_range(start_season: str | int, end_season: str | int) -> list[int]:
    """Every season id from start_season through end_season, inclusive."""
    start_int = parse_season(start_season)
    end_int = parse_season(end_season)
    start_year, _ = season_years(start_int)
    end_year, _ = season_years(end_int)
    if end_year < start_year:
        raise ValueError(f"end_season ({end_season}) precedes start_season ({start_season})")
    return [int(f"{y}{y + 1}") for y in range(start_year, end_year + 1)]


def season_date_bounds(season: int) -> tuple[str, str]:
    """Approximate [start, end) calendar-date bounds for a season, generous enough to
    cover preseason through the Stanley Cup Final. Not clipped to "today" - callers
    should do that themselves for the current/future season.
    """
    start_year, end_year = season_years(season)
    return f"{start_year}-09-01", f"{end_year}-08-15"


def containing_season(game_date: str) -> int:
    """The NHL season id that a given YYYY-MM-DD calendar date falls within."""
    d = date.fromisoformat(game_date)
    start_year = d.year if d.month >= 7 else d.year - 1
    return int(f"{start_year}{start_year + 1}")
