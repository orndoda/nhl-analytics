-- name: games_score_ties
-- severity: fail
-- description: Every completed regular-season or playoff game (game_type 2/3)
--   must have a winner - the NHL has used OT/shootout to break ties since 2005.
--   An equal-score completed game means the score was mis-flattened.
SELECT game_id, season, game_type, game_date, home_team_abbrev, away_team_abbrev, home_score, away_score
FROM games
WHERE game_state IN ('OFF', 'FINAL')
  AND game_type IN (2, 3)
  AND home_score = away_score
ORDER BY game_date;
