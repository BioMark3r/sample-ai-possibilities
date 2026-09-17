"""Validated, external tactical configuration for lab-only experiments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROLES = ("gk", "def", "mid", "fwd1", "fwd2")
ALLOWED = {"instructions", "parameters"}


@dataclass(frozen=True)
class TacticalConfig:
    name: str
    team: str
    global_settings: dict
    roles: dict[str, dict]
    path: str | None = None

    def settings_for(self, role: str) -> dict:
        """Merge global settings with one role override without mutating either."""
        merged = {"instructions": list(self.global_settings.get("instructions", [])),
                  "parameters": dict(self.global_settings.get("parameters", {}))}
        override = self.roles.get(role, {})
        merged["instructions"].extend(override.get("instructions", []))
        merged["parameters"].update(override.get("parameters", {}))
        return merged

    def to_dict(self) -> dict:
        return {"name": self.name, "team": self.team, "global": self.global_settings,
                "roles": self.roles, "path": self.path}


def _settings(value, where):
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - ALLOWED:
        raise ValueError(f"{where} must contain only instructions and parameters")
    instructions = value.get("instructions", [])
    parameters = value.get("parameters", {})
    if not isinstance(instructions, list) or not all(isinstance(item, str) and item.strip() for item in instructions):
        raise ValueError(f"{where}.instructions must be an array of non-empty strings")
    if not isinstance(parameters, dict) or not all(isinstance(key, str) for key in parameters):
        raise ValueError(f"{where}.parameters must be an object with string keys")
    return {"instructions": instructions, "parameters": parameters}


def load_config(value: str | Path, configs_dir: str | Path | None = None) -> TacticalConfig:
    """Load a path or a named JSON document from ``configs_dir``."""
    supplied = Path(value)
    base = Path(configs_dir) if configs_dir else Path(__file__).resolve().parents[1] / "configs"
    path = supplied if supplied.exists() else base / (supplied.name if supplied.suffix else f"{supplied.name}.json")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not load tactical configuration {value!s}: {error}") from error
    if not isinstance(document, dict):
        raise ValueError("configuration must be a JSON object")
    unknown_roles = set(document.get("roles", {})) - set(ROLES)
    if unknown_roles:
        raise ValueError(f"unknown role overrides: {', '.join(sorted(unknown_roles))}")
    name, team = document.get("name"), document.get("team", "balanced")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("configuration.name must be a non-empty string")
    if team != "balanced":
        raise ValueError("Phase 3 tactical configurations currently require team 'balanced'")
    roles = document.get("roles", {})
    if not isinstance(roles, dict):
        raise ValueError("configuration.roles must be an object")
    return TacticalConfig(name, team, _settings(document.get("global"), "global"),
                          {role: _settings(settings, f"roles.{role}") for role, settings in roles.items()}, str(path))


def tactical_addendum(config: TacticalConfig, role: str) -> str:
    settings = config.settings_for(role)
    lines = list(settings["instructions"])
    lines.extend(f"{key}: {json.dumps(value, sort_keys=True)}"
                 for key, value in sorted(settings["parameters"].items()))
    if not lines:
        return ""
    return "\n\n## Lab tactical experiment instructions\n" + "\n".join(f"- {line}" for line in lines)
