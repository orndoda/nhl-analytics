-- name: season_coverage
-- severity: info
-- description: Per-season row counts across the core tables, for eyeballing which
--   seasons look thin. Regular-season (game_type=2) game counts should land near
--   1230 (30 teams), 1271 (31 teams), 1082/868 (2019-20/2020-21, COVID-shortened),
--   or 1312 (32 teams) depending on era.
SELECT
    g.season,
    count(*) FILTER (WHERE g.game_type = 2) AS regular_season_games,
    count(*) FILTER (WHERE g.game_type = 3) AS playoff_games,
    (SELECT count(*) FROM standings s WHERE s.season = g.season) AS standings_rows,
    (SELECT count(*) FROM rosters r WHERE r.season = g.season) AS roster_rows,
    (SELECT count(*) FROM playbyplay p JOIN games gg ON gg.game_id = p.game_id WHERE gg.season = g.season) AS playbyplay_rows
FROM games g
GROUP BY g.season
ORDER BY g.season;
