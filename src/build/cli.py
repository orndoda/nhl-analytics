"""Command-line interface for the NHL data build pipeline.

    python -m src.build backfill --db-name nhl --db-user nhl --db-password ...
    python -m src.build update --db-name nhl --db-user nhl --db-password ...

Database credentials can be supplied, in order of precedence:
  1. --db-user / --db-password
  2. the standard libpq environment variables ($PGUSER, $PGPASSWORD)
  3. a --secrets-file YAML file (default: <repo root>/secret.yaml) shaped like:
         DATABASE:
           USER: myuser
           PASSWORD: mypassword
If a password still isn't found by any of the above, you'll be prompted for one.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

import yaml

from . import db, pipeline, seasons
from .nhl_client import build_client

DEFAULT_SECRETS_FILE = Path(__file__).resolve().parents[2] / "secret.yaml"


def _add_db_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("database")
    group.add_argument(
        "--db-name", default=os.environ.get("PGDATABASE"),
        help="Postgres database name (or set $PGDATABASE)",
    )
    group.add_argument(
        "--db-user", default=None,
        help="Postgres user (or set $PGUSER, or provide DATABASE.USER in --secrets-file)",
    )
    group.add_argument(
        "--db-password", default=None,
        help="Postgres password (or set $PGPASSWORD, or provide DATABASE.PASSWORD in "
        "--secrets-file; prompted if omitted)",
    )
    group.add_argument(
        "--db-host", default=os.environ.get("PGHOST", "localhost"),
        help="Postgres server host (default: localhost)",
    )
    group.add_argument(
        "--db-port", type=int, default=int(os.environ.get("PGPORT", 5432)),
        help="Postgres server port (default: 5432)",
    )
    group.add_argument(
        "--secrets-file", default=str(DEFAULT_SECRETS_FILE),
        help="YAML file with DATABASE.USER / DATABASE.PASSWORD, used as a fallback when "
        f"--db-user/--db-password (and $PGUSER/$PGPASSWORD) aren't set (default: {DEFAULT_SECRETS_FILE}). "
        "Pass an empty string to disable.",
    )


def _load_secrets_file(path: Path) -> dict:
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    database = data.get("DATABASE") or {}
    return {"user": database.get("USER"), "password": database.get("PASSWORD")}


def _resolve_credentials(args: argparse.Namespace) -> tuple[str, str]:
    user = args.db_user or os.environ.get("PGUSER")
    password = args.db_password or os.environ.get("PGPASSWORD")

    if (not user or not password) and args.secrets_file:
        secrets_path = Path(args.secrets_file)
        if secrets_path.is_file():
            secrets = _load_secrets_file(secrets_path)
            user = user or secrets["user"]
            password = password or secrets["password"]
        elif secrets_path != DEFAULT_SECRETS_FILE:
            sys.exit(f"error: --secrets-file {secrets_path} not found")

    if not user:
        sys.exit(
            "error: --db-user is required (or set $PGUSER, or provide DATABASE.USER in --secrets-file)"
        )
    if not password:
        password = getpass.getpass(f"Postgres password for {user}@{args.db_host}: ")

    return user, password


def _connect(args: argparse.Namespace):
    if not args.db_name:
        sys.exit("error: --db-name is required (or set $PGDATABASE)")

    user, password = _resolve_credentials(args)

    conn = db.connect(
        host=args.db_host, port=args.db_port, dbname=args.db_name, user=user, password=password,
    )
    db.create_schema(conn)
    return conn


def _cmd_backfill(args: argparse.Namespace) -> None:
    conn = _connect(args)
    client = build_client()
    try:
        summary = pipeline.run_backfill(
            client,
            conn,
            start_season=args.start_season,
            end_season=args.end_season,
            skip_playbyplay=args.skip_playbyplay,
            skip_players=args.skip_players,
            force_playbyplay=args.force,
        )
    finally:
        conn.close()
    print(summary)


def _cmd_update(args: argparse.Namespace) -> None:
    conn = _connect(args)
    client = build_client()
    try:
        summary = pipeline.run_update(
            client,
            conn,
            lookback_days=args.lookback_days,
            overlap_days=args.overlap_days,
            skip_players=args.skip_players,
        )
    finally:
        conn.close()
    print(summary)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.build", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_backfill = sub.add_parser(
        "backfill",
        help="Full historical load for a season range (default 2013-2014 through 2025-2026)",
    )
    _add_db_args(p_backfill)
    p_backfill.add_argument("--start-season", default=seasons.EARLIEST_SEASON, help="e.g. 2013-2014")
    p_backfill.add_argument("--end-season", default="2025-2026", help="e.g. 2025-2026")
    p_backfill.add_argument(
        "--skip-playbyplay", action="store_true", help="Skip the per-game play-by-play load",
    )
    p_backfill.add_argument(
        "--skip-players", action="store_true", help="Skip fetching player bios",
    )
    p_backfill.add_argument(
        "--force", action="store_true",
        help="Re-fetch play-by-play even for games already loaded",
    )
    p_backfill.set_defaults(func=_cmd_backfill)

    p_update = sub.add_parser(
        "update",
        help="Incrementally fill in the most recent games/weeks since the last load",
    )
    _add_db_args(p_update)
    p_update.add_argument(
        "--lookback-days", type=int, default=None,
        help="Rescan a fixed trailing window instead of resuming from the latest stored game_date",
    )
    p_update.add_argument(
        "--overlap-days", type=int, default=3,
        help="Days of overlap before the latest stored game_date, to catch late corrections (default 3)",
    )
    p_update.add_argument(
        "--skip-players", action="store_true", help="Skip fetching player bios",
    )
    p_update.set_defaults(func=_cmd_update)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
