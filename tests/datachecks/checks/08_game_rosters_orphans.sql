-- name: game_rosters_orphans
-- severity: fail
-- description: Every game_rosters row's game_id must exist in `games`, mirroring
--   the playbyplay_orphans check for the per-game roster table.
SELECT gr.game_id, count(*) AS roster_spot_rows
FROM game_rosters gr
LEFT JOIN games g ON g.game_id = gr.game_id
WHERE g.game_id IS NULL
GROUP BY gr.game_id
ORDER BY gr.game_id;
