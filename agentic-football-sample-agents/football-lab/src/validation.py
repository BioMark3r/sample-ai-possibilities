"""Strict reporting validation for the existing command contract."""

from __future__ import annotations

from dataclasses import dataclass, field

COMMAND_PARAMETERS = {
    "MOVE_TO": {"target_x": (int, float), "target_y": (int, float), "sprint": bool},
    "PASS": {"target_player_id": int, "type": str},
    "SHOOT": {"aim_location": str, "power": (int, float)},
    "SLIDE_TACKLE": {"target_player_id": int, "sprint": bool, "distance": (int, float)},
    "PRESS_BALL": {"intensity": (int, float)}, "INTERCEPT": {"aggressive": bool},
    "MARK": {"target_player_id": int, "tightness": str},
    "FOLLOW_PLAYER": {"target_player_id": int, "target_team": str, "distance": (int, float)},
    "GK_DISTRIBUTE": {"target_player_id": int, "method": str},
    "SET_STANCE": {"stance": int}, "CLEAR_OVERRIDE": {}, "RESET": {},
}


@dataclass
class Validation:
    valid: bool
    errors: list[str] = field(default_factory=list)
    action_type: str | None = None
    details: dict = field(default_factory=dict)


def validate_scenario(value) -> list[str]:
    errors = []
    if not isinstance(value, dict):
        return ["scenario must be a JSON object"]
    if not isinstance(value.get("gameState"), dict):
        errors.append("gameState must be an object")
    elif not isinstance(value["gameState"].get("ball"), dict):
        errors.append("gameState.ball must be an object")
    elif not isinstance(value["gameState"].get("players"), list):
        errors.append("gameState.players must be an array")
    if not isinstance(value.get("teamId", 0), int):
        errors.append("teamId must be an integer")
    if "myPlayers" in value and not isinstance(value["myPlayers"], list):
        errors.append("myPlayers must be an array")
    return errors


def validate_commands(commands) -> Validation:
    if not isinstance(commands, list) or not commands:
        return Validation(False, ["action must be a non-empty command array"])
    errors = []
    first_type = commands[0].get("commandType") if isinstance(commands[0], dict) else None
    details = {}
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            errors.append(f"command {index} must be an object")
            continue
        action_type = command.get("commandType")
        if action_type not in COMMAND_PARAMETERS:
            errors.append(f"command {index} has unknown commandType {action_type!r}")
            continue
        for key in ("playerId", "teamId"):
            if not isinstance(command.get(key), int):
                errors.append(f"command {index}.{key} must be an integer")
        parameters = command.get("parameters")
        if not isinstance(parameters, dict):
            errors.append(f"command {index}.parameters must be an object")
            continue
        for key, expected in COMMAND_PARAMETERS[action_type].items():
            if not isinstance(parameters.get(key), expected) or isinstance(parameters.get(key), bool) and expected != bool:
                errors.append(f"command {index}.parameters.{key} has the wrong type or is missing")
        details = parameters
    return Validation(not errors, errors, first_type, details)
