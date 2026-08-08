-- name: duplicate_keys
-- severity: fail
-- description: Sanity check that each table's primary key is actually unique in
--   practice (belt-and-braces on top of the DB constraint - would only fire if
--   the schema's PRIMARY KEY was altered or dropped out from under the data).
SELECT 'games' AS table_name, game_id::text AS key, count(*) AS cnt
FROM games GROUP BY game_id HAVING count(*) > 1
UNION ALL
SELECT 'schedules', game_id::text, count(*)
FROM schedules GROUP BY game_id HAVING count(*) > 1
UNION ALL
SELECT 'standings', standings_date::text || '/' || team_abbrev, count(*)
FROM standings GROUP BY standings_date, team_abbrev HAVING count(*) > 1
UNION ALL
SELECT 'rosters', season::text || '/' || team_abbrev || '/' || player_id::text, count(*)
FROM rosters GROUP BY season, team_abbrev, player_id HAVING count(*) > 1
UNION ALL
SELECT 'players', player_id::text, count(*)
FROM players GROUP BY player_id HAVING count(*) > 1
UNION ALL
SELECT 'playbyplay', game_id::text || '/' || event_id::text, count(*)
FROM playbyplay GROUP BY game_id, event_id HAVING count(*) > 1
UNION ALL
SELECT 'game_rosters', game_id::text || '/' || player_id::text, count(*)
FROM game_rosters GROUP BY game_id, player_id HAVING count(*) > 1
UNION ALL
SELECT 'teams', team_id::text, count(*)
FROM teams GROUP BY team_id HAVING count(*) > 1;
