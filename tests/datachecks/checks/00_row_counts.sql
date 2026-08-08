-- name: row_counts
-- severity: info
-- description: Row counts for every table, as a quick sanity glance at what's loaded.
SELECT 'teams' AS table_name, count(*) AS rows FROM teams
UNION ALL SELECT 'schedules', count(*) FROM schedules
UNION ALL SELECT 'games', count(*) FROM games
UNION ALL SELECT 'standings', count(*) FROM standings
UNION ALL SELECT 'rosters', count(*) FROM rosters
UNION ALL SELECT 'players', count(*) FROM players
UNION ALL SELECT 'playbyplay', count(*) FROM playbyplay
UNION ALL SELECT 'game_rosters', count(*) FROM game_rosters
ORDER BY 1;
