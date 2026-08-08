-- name: regular_season_game_counts
-- severity: fail
-- description: Regular-season (game_type=2) game counts per season should fall
--   within a generous historical band (700-1400: covers the COVID-shortened
--   2019-20/2020-21 seasons through the full 32-team, 1312-game slate). Anything
--   outside that points at a partial/interrupted backfill for that season.
SELECT season, count(*) AS regular_season_games
FROM games
WHERE game_type = 2
GROUP BY season
HAVING count(*) NOT BETWEEN 700 AND 1400
ORDER BY 1;
