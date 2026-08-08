"""Flatten raw NHL API JSON payloads into flat row dicts matching the columns
defined in `db.SCHEMA`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default(field: dict | None) -> str | None:
    """Pull the "default" locale string out of an NHL API {"default": ..., "fr": ...} dict."""
    return (field or {}).get("default")


# --------------------------------------------------------------------------- #
# schedules / games / teams  (sourced from the weekly schedule scan)
# --------------------------------------------------------------------------- #

def flatten_schedule_game(game: dict, day_date: str) -> dict:
    away = game.get("awayTeam") or {}
    home = game.get("homeTeam") or {}
    return {
        "game_id": int(game["id"]),
        "season": game.get("season"),
        "game_type": game.get("gameType"),
        "game_date": day_date,
        "start_time_utc": game.get("startTimeUTC"),
        "venue": _default(game.get("venue")),
        "venue_timezone": game.get("venueTimezone"),
        "neutral_site": game.get("neutralSite"),
        "away_team_id": away.get("id"),
        "away_team_abbrev": away.get("abbrev"),
        "home_team_id": home.get("id"),
        "home_team_abbrev": home.get("abbrev"),
        "game_state": game.get("gameState"),
        "game_schedule_state": game.get("gameScheduleState"),
        "tv_broadcasts": json.dumps(game.get("tvBroadcasts") or []),
        "updated_at": _now(),
    }


def flatten_game_result(game: dict, day_date: str) -> dict:
    away = game.get("awayTeam") or {}
    home = game.get("homeTeam") or {}
    period_descriptor = game.get("periodDescriptor") or {}
    outcome = game.get("gameOutcome") or {}
    winning_goalie = game.get("winningGoalie") or {}
    winning_scorer = game.get("winningGoalScorer") or {}
    return {
        "game_id": int(game["id"]),
        "season": game.get("season"),
        "game_type": game.get("gameType"),
        "game_date": day_date,
        "venue": _default(game.get("venue")),
        "away_team_id": away.get("id"),
        "away_team_abbrev": away.get("abbrev"),
        "away_score": away.get("score"),
        "home_team_id": home.get("id"),
        "home_team_abbrev": home.get("abbrev"),
        "home_score": home.get("score"),
        "game_state": game.get("gameState"),
        "game_schedule_state": game.get("gameScheduleState"),
        "periods_played": period_descriptor.get("number"),
        "final_period_type": outcome.get("lastPeriodType"),
        "winning_goalie_id": winning_goalie.get("playerId"),
        "winning_goal_scorer_id": winning_scorer.get("playerId"),
        "updated_at": _now(),
    }


def flatten_teams_from_schedule_game(game: dict) -> list[dict]:
    """Extract the home/away team dimension rows embedded in a schedule game dict."""
    rows = []
    for side in ("awayTeam", "homeTeam"):
        team = game.get(side) or {}
        if team.get("id") is None:
            continue
        rows.append(
            {
                "team_id": team["id"],
                "abbrev": team.get("abbrev"),
                "common_name": _default(team.get("commonName")),
                "place_name": _default(team.get("placeName")),
                "updated_at": _now(),
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# standings
# --------------------------------------------------------------------------- #

def flatten_standings_entry(entry: dict) -> dict:
    return {
        "standings_date": entry.get("date"),
        "team_abbrev": _default(entry.get("teamAbbrev")),
        "season": entry.get("seasonId"),
        "game_type_id": entry.get("gameTypeId"),
        "team_name": _default(entry.get("teamName")),
        "team_common_name": _default(entry.get("teamCommonName")),
        "conference_abbrev": entry.get("conferenceAbbrev"),
        "division_abbrev": entry.get("divisionAbbrev"),
        "games_played": entry.get("gamesPlayed"),
        "wins": entry.get("wins"),
        "losses": entry.get("losses"),
        "ot_losses": entry.get("otLosses"),
        "ties": entry.get("ties"),
        "points": entry.get("points"),
        "point_pctg": entry.get("pointPctg"),
        "regulation_wins": entry.get("regulationWins"),
        "regulation_plus_ot_wins": entry.get("regulationPlusOtWins"),
        "goal_for": entry.get("goalFor"),
        "goal_against": entry.get("goalAgainst"),
        "goal_differential": entry.get("goalDifferential"),
        "streak_code": entry.get("streakCode"),
        "streak_count": entry.get("streakCount"),
        "league_sequence": entry.get("leagueSequence"),
        "conference_sequence": entry.get("conferenceSequence"),
        "division_sequence": entry.get("divisionSequence"),
        "wildcard_sequence": entry.get("wildcardSequence"),
        "updated_at": _now(),
    }


# --------------------------------------------------------------------------- #
# rosters (season-level team roster) / players (bio dimension)
# --------------------------------------------------------------------------- #

def flatten_roster_player(season: int, team_abbrev: str, player: dict, position_group: str) -> dict:
    return {
        "season": season,
        "team_abbrev": team_abbrev,
        "player_id": player.get("id"),
        "first_name": _default(player.get("firstName")),
        "last_name": _default(player.get("lastName")),
        "sweater_number": player.get("sweaterNumber"),
        "position_code": player.get("positionCode"),
        "position_group": position_group,
        "shoots_catches": player.get("shootsCatches"),
        "height_in_inches": player.get("heightInInches"),
        "weight_in_pounds": player.get("weightInPounds"),
        "birth_date": player.get("birthDate"),
        "birth_city": _default(player.get("birthCity")),
        "birth_country": player.get("birthCountry"),
        "birth_state_province": _default(player.get("birthStateProvince")),
        "updated_at": _now(),
    }


def flatten_player_bio(payload: dict) -> dict:
    draft = payload.get("draftDetails") or {}
    return {
        "player_id": payload.get("playerId"),
        "first_name": _default(payload.get("firstName")),
        "last_name": _default(payload.get("lastName")),
        "position": payload.get("position"),
        "is_active": payload.get("isActive"),
        "current_team_abbrev": payload.get("currentTeamAbbrev"),
        "sweater_number": payload.get("sweaterNumber"),
        "height_in_inches": payload.get("heightInInches"),
        "weight_in_pounds": payload.get("weightInPounds"),
        "birth_date": payload.get("birthDate"),
        "birth_city": _default(payload.get("birthCity")),
        "birth_country": payload.get("birthCountry"),
        "birth_state_province": _default(payload.get("birthStateProvince")),
        "shoots_catches": payload.get("shootsCatches"),
        "draft_year": draft.get("year"),
        "draft_round": draft.get("round"),
        "draft_overall": draft.get("overallPick"),
        "draft_team_abbrev": draft.get("teamAbbrev"),
        "updated_at": _now(),
    }


# --------------------------------------------------------------------------- #
# playbyplay / game_rosters (per-game, from the play-by-play payload)
# --------------------------------------------------------------------------- #

def flatten_play(game_id: int, play: dict) -> dict:
    period = play.get("periodDescriptor") or {}
    details = play.get("details") or {}
    return {
        "game_id": game_id,
        "event_id": play.get("eventId"),
        "sort_order": play.get("sortOrder"),
        "period": period.get("number"),
        "period_type": period.get("periodType"),
        "time_in_period": play.get("timeInPeriod"),
        "time_remaining": play.get("timeRemaining"),
        "situation_code": play.get("situationCode"),
        "home_team_defending_side": play.get("homeTeamDefendingSide"),
        "type_code": play.get("typeCode"),
        "type_desc_key": play.get("typeDescKey"),
        "x_coord": details.get("xCoord"),
        "y_coord": details.get("yCoord"),
        "zone_code": details.get("zoneCode"),
        "event_owner_team_id": details.get("eventOwnerTeamId"),
        "shot_type": details.get("shotType"),
        "reason": details.get("reason"),
        "secondary_reason": details.get("secondaryReason"),
        "scoring_player_id": details.get("scoringPlayerId"),
        "scoring_player_total": details.get("scoringPlayerTotal"),
        "assist1_player_id": details.get("assist1PlayerId"),
        "assist1_player_total": details.get("assist1PlayerTotal"),
        "assist2_player_id": details.get("assist2PlayerId"),
        "assist2_player_total": details.get("assist2PlayerTotal"),
        "goalie_in_net_id": details.get("goalieInNetId"),
        "shooting_player_id": details.get("shootingPlayerId"),
        "blocking_player_id": details.get("blockingPlayerId"),
        "hitting_player_id": details.get("hittingPlayerId"),
        "hittee_player_id": details.get("hitteePlayerId"),
        "winning_player_id": details.get("winningPlayerId"),
        "losing_player_id": details.get("losingPlayerId"),
        "player_id": details.get("playerId"),
        "committed_by_player_id": details.get("committedByPlayerId"),
        "drawn_by_player_id": details.get("drawnByPlayerId"),
        "served_by_player_id": details.get("servedByPlayerId"),
        "penalty_severity": details.get("typeCode"),
        "penalty_desc_key": details.get("descKey"),
        "penalty_duration": details.get("duration"),
        "away_score": details.get("awayScore"),
        "home_score": details.get("homeScore"),
        "away_sog": details.get("awaySOG"),
        "home_sog": details.get("homeSOG"),
    }


def flatten_roster_spot(game_id: int, spot: dict) -> dict:
    return {
        "game_id": game_id,
        "player_id": spot.get("playerId"),
        "team_id": spot.get("teamId"),
        "first_name": _default(spot.get("firstName")),
        "last_name": _default(spot.get("lastName")),
        "sweater_number": spot.get("sweaterNumber"),
        "position_code": spot.get("positionCode"),
    }
