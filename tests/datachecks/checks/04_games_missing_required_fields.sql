-- name: games_missing_required_fields
-- severity: fail
-- description: Completed games (game_state OFF/FINAL) must have both team
--   abbreviations and both scores populated - these come straight off the
--   schedule payload, so a null here means the flatten/upsert step is broken.
SELECT game_id, season, game_date, home_team_abbrev, away_team_abbrev, home_score, away_score, game_state
FROM games
WHERE game_state IN ('OFF', 'FINAL')
  AND (
      home_team_abbrev IS NULL OR away_team_abbrev IS NULL
      OR home_score IS NULL OR away_score IS NULL
      OR game_date IS NULL
  )
ORDER BY game_date;
