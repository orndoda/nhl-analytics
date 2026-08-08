-- name: game_rosters_players_orphans
-- severity: warn
-- description: Every player_id referenced by `game_rosters` should ideally have a
--   bio row in `players`. Warn (not fail) because per-game rosters can include
--   edge cases like emergency backup goalies whose bio the landing endpoint
--   sometimes 404s on.
SELECT DISTINCT gr.player_id, gr.first_name, gr.last_name
FROM game_rosters gr
LEFT JOIN players p ON p.player_id = gr.player_id
WHERE p.player_id IS NULL
ORDER BY gr.player_id;
