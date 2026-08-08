-- name: roster_size_outliers
-- severity: warn
-- description: Seasons whose `rosters` row count is less than 60% of the median
--   across all loaded seasons. Team/roster counts drift a bit year to year
--   (expansion, roster churn), but a season far below the pack usually means
--   `sync_rosters` only saw a subset of that season's teams (e.g. an `update`
--   run with a narrow date window) rather than a true full-season roster pull.
WITH per_season AS (
    SELECT season, count(*) AS roster_rows
    FROM rosters
    GROUP BY season
),
stats AS (
    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY roster_rows) AS median_rows
    FROM per_season
)
SELECT per_season.season, per_season.roster_rows, stats.median_rows
FROM per_season, stats
WHERE per_season.roster_rows < 0.6 * stats.median_rows
ORDER BY per_season.season;
