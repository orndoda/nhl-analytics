-- name: rosters_players_orphans
-- severity: fail
-- description: Every player_id referenced by `rosters` should have a bio row in
--   `players` - `sync_players` is driven off exactly this union, so a gap means
--   the players step didn't run (or failed) after rosters were loaded.
SELECT DISTINCT r.player_id, r.first_name, r.last_name, r.season, r.team_abbrev
FROM rosters r
LEFT JOIN players p ON p.player_id = r.player_id
WHERE p.player_id IS NULL
ORDER BY r.player_id;
