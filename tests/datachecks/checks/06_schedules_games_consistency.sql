-- name: schedules_games_consistency
-- severity: fail
-- description: Every game marked OFF/FINAL in `schedules` should have a matching
--   row in `games` - both are populated from the same schedule scan, so a gap
--   here means the games-table upsert was skipped for that game.
SELECT s.game_id, s.season, s.game_date, s.home_team_abbrev, s.away_team_abbrev, s.game_state
FROM schedules s
LEFT JOIN games g ON g.game_id = s.game_id
WHERE s.game_state IN ('OFF', 'FINAL')
  AND g.game_id IS NULL
ORDER BY s.game_date;
