-- name: players_missing_birthdate
-- severity: warn
-- description: Players with no birth_date on file. Informational data-completeness
--   signal (the landing endpoint occasionally omits bio fields), not necessarily
--   a pipeline bug.
SELECT player_id, first_name, last_name, position, current_team_abbrev
FROM players
WHERE birth_date IS NULL
ORDER BY player_id;
