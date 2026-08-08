-- name: missing_seasons
-- severity: fail
-- description: Every NHL season between the earliest and latest season already in
--   `schedules` should have at least one row. A season id present in this result
--   was skipped entirely - re-run backfill for it.
WITH bounds AS (
    SELECT (min(season)::text)::int / 10000 AS start_year,
           (max(season)::text)::int / 10000 AS end_year
    FROM schedules
),
expected AS (
    SELECT (y::text || (y + 1)::text)::int AS season
    FROM bounds, generate_series(bounds.start_year, bounds.end_year) AS y
)
SELECT expected.season AS missing_season
FROM expected
LEFT JOIN (SELECT DISTINCT season FROM schedules) actual ON actual.season = expected.season
WHERE actual.season IS NULL
ORDER BY 1;
