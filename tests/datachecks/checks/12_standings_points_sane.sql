-- name: standings_points_sane
-- severity: fail
-- description: Under the NHL's point system a team can earn at most 2 points per
--   game played (regulation/OT/SO win) and never a negative number - bounds that
--   should hold for every standings snapshot regardless of era.
SELECT standings_date, team_abbrev, season, games_played, points
FROM standings
WHERE points IS NULL
   OR games_played IS NULL
   OR points < 0
   OR points > 2 * games_played
ORDER BY standings_date;
