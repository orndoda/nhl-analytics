-- name: playbyplay_orphans
-- severity: fail
-- description: Every playbyplay row's game_id must exist in `games`. A non-empty
--   result means play-by-play was loaded for a game that games/schedules doesn't
--   know about (stale game_id, or a manual/partial load).
SELECT p.game_id, count(*) AS play_rows
FROM playbyplay p
LEFT JOIN games g ON g.game_id = p.game_id
WHERE g.game_id IS NULL
GROUP BY p.game_id
ORDER BY p.game_id;
