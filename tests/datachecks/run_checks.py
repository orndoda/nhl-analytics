"""Run the data-quality checks in tests/datachecks/checks/ against a filled NHL
Postgres database, e.g. after:

    python -m src.build backfill --db-name nhl

Usage:

    python tests/datachecks/run_checks.py --db-name nhl
    python tests/datachecks/run_checks.py --db-name nhl --db-user nhl --db-password ...

Credential resolution matches `python -m src.build` exactly (same --db-* flags,
same precedence: CLI flag > $PGUSER/$PGPASSWORD > --secrets-file, default
<repo root>/secret.yaml > interactive prompt).

Each .sql file in checks/ is a single query preceded by a small metadata header:

    -- name: some_check_name
    -- severity: fail | warn | info
    -- description: one line explaining what a non-empty result means

`fail`/`warn` queries should return the *offending* rows - any row returned is
a violation. `info` queries are just printed for context (row counts, season
coverage, ...) regardless of what they return. Exits non-zero iff any `fail`
check returned rows.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.build.cli import _add_db_args, _resolve_credentials  # noqa: E402

CHECKS_DIR = Path(__file__).resolve().parent / "checks"
DEFAULT_SAMPLE_ROWS = 10
SEVERITIES = {"fail", "warn", "info"}
HEADER_RE = re.compile(r"^--\s*(\w+):\s*(.*)$")


@dataclass
class Check:
    path: Path
    name: str
    severity: str
    description: str
    sql: str


def load_check(path: Path) -> Check:
    lines = path.read_text().splitlines()
    meta: dict[str, str] = {}
    body_start = len(lines)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        m = HEADER_RE.match(stripped)
        if not m:
            body_start = i
            break
        meta[m.group(1).lower()] = m.group(2).strip()

    sql = "\n".join(lines[body_start:]).strip()
    if not sql:
        raise ValueError(f"{path}: no SQL body found after the header comments")

    severity = meta.get("severity", "fail").lower()
    if severity not in SEVERITIES:
        raise ValueError(f"{path}: severity must be one of {sorted(SEVERITIES)}, got {severity!r}")

    return Check(path=path, name=meta.get("name", path.stem), severity=severity,
                 description=meta.get("description", ""), sql=sql)


def load_checks(checks_dir: Path) -> list[Check]:
    return [load_check(p) for p in sorted(checks_dir.glob("*.sql"))]


def format_row(columns: list[str], row: tuple) -> str:
    return ", ".join(f"{c}={v}" for c, v in zip(columns, row))


def print_rows(columns: list[str], rows: list[tuple], sample_rows: int, indent: str = "       ") -> None:
    for row in rows[:sample_rows]:
        print(f"{indent}{format_row(columns, row)}")
    if len(rows) > sample_rows:
        print(f"{indent}... ({len(rows) - sample_rows} more row(s))")


def run_checks(conn, checks: list[Check], sample_rows: int) -> int:
    """Run every check, print a report, and return an exit code (0 if nothing failed)."""
    failed, warned, passed, info_count = [], [], [], 0

    for check in checks:
        with conn.cursor() as cur:
            cur.execute(check.sql)
            columns = [d.name for d in cur.description] if cur.description else []
            rows = cur.fetchall()

        if check.severity == "info":
            info_count += 1
            print(f"[INFO] {check.name}  ({len(rows)} row(s))")
            if check.description:
                print(f"       {check.description}")
            print_rows(columns, rows, sample_rows)
            print()
            continue

        ok = not rows
        status = "PASS" if ok else ("FAIL" if check.severity == "fail" else "WARN")
        print(f"[{status}] {check.name}  ({len(rows)} offending row(s))")
        if check.description:
            print(f"       {check.description}")
        if rows:
            print_rows(columns, rows, sample_rows)
        print()

        (passed if ok else failed if status == "FAIL" else warned).append(check.name)

    evaluated = len(checks) - info_count
    print("=" * 72)
    print(
        f"{evaluated} check(s) evaluated ({info_count} info): "
        f"{len(passed)} passed, {len(warned)} warned, {len(failed)} failed"
    )
    if warned:
        print("Warned:", ", ".join(warned))
    if failed:
        print("Failed:", ", ".join(failed))

    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python tests/datachecks/run_checks.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_db_args(parser)
    parser.add_argument("--checks-dir", default=str(CHECKS_DIR), help="Directory of .sql check files")
    parser.add_argument(
        "--sample-rows", type=int, default=DEFAULT_SAMPLE_ROWS,
        help="Max offending rows to print per check (default 10)",
    )
    args = parser.parse_args(argv)

    if not args.db_name:
        sys.exit("error: --db-name is required (or set $PGDATABASE)")

    user, password = _resolve_credentials(args)
    conn = psycopg.connect(
        host=args.db_host, port=args.db_port, dbname=args.db_name, user=user, password=password,
    )

    checks = load_checks(Path(args.checks_dir))
    if not checks:
        sys.exit(f"error: no .sql checks found in {args.checks_dir}")

    try:
        return run_checks(conn, checks, args.sample_rows)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
