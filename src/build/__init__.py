"""Build and maintain a Postgres warehouse of NHL data (games, standings,
rosters, schedules, players, play-by-play) sourced from the NHL API.

See ``src/build/cli.py`` for the command-line entry points, or run:

    python -m src.build backfill --db-name nhl --db-user nhl --db-password ...
    python -m src.build update --db-name nhl --db-user nhl --db-password ...
"""
