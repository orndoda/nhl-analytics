-- name: completed_games_missing_playbyplay
-- severity: warn
-- description: Completed (OFF/FINAL) games with zero playbyplay rows. Usually
--   means the play-by-play fetch failed or 404'd for that game (older seasons,
--   All-Star/exhibition formats) - review and consider `backfill --force` for
--   these specific games if the NHL API does have data for them.
SELECT g.game_id, g.season, g.game_type, g.game_date, g.home_team_abbrev, g.away_team_abbrev
FROM games g
LEFT JOIN (SELECT DISTINCT game_id FROM playbyplay) p ON p.game_id = g.game_id
WHERE g.game_state IN ('OFF', 'FINAL')
  AND p.game_id IS NULL
ORDER BY g.game_date;
