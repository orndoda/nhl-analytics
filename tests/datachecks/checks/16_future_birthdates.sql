-- name: future_birthdates
-- severity: fail
-- description: A player's birth_date can never be in the future - a hit here
--   means a date field got mis-mapped somewhere in the flatten step.
SELECT player_id, first_name, last_name, birth_date
FROM players
WHERE birth_date > CURRENT_DATE
ORDER BY player_id;
