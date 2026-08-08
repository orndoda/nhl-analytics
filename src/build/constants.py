"""Shared constants for the NHL data build pipeline."""

# gameType: 1 = preseason, 2 = regular season, 3 = playoffs
DEFAULT_GAME_TYPES = (2, 3)

# gameState values that indicate a game is officially over and its boxscore/play-by-play
# are stable.
FINAL_GAME_STATES = {"OFF", "FINAL"}

# Position groups as returned by the roster endpoint's top-level keys.
ROSTER_POSITION_GROUPS = ("forwards", "defensemen", "goalies")
