#!/usr/bin/env python3
"""
Raphael YAML Configuration Validator.

Validates raphael.yaml against a strict schema. Fails on unknown keys.
Supports RAPHAEL_ environment variable overrides.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""


# Strict schema definition
SCHEMA = {
    "version": {"type": str, "required": True},
    "target": {
        "type": dict,
        "required": False,
        "schema": {
            "host": {"type": str, "required": False},
            "port": {"type": int, "required": False},
            "platform": {"type": str, "required": False},
            "architecture": {"type": str, "required": False},
        },
    },
    "authorization": {
        "type": dict,
        "required": False,
        "schema": {
            "engagement_id": {"type": str, "required": False},
            "allowed_scopes": {"type": list, "required": False},
            "prohibited_targets": {"type": list, "required": False},
            "allowed_action_types": {"type": list, "required": False},
            "prohibited_action_types": {"type": list, "required": False},
            "allowed_capabilities": {"type": list, "required": False},
            "prohibited_capabilities": {"type": list, "required": False},
            "rate_limits": {
                "type": dict,
                "required": False,
                "schema": {
                    "max_actions_per_minute": {"type": int, "required": False},
                    "max_actions_per_hour": {"type": int, "required": False},
                    "max_concurrent": {"type": int, "required": False},
                },
            },
            "impact_budget": {
                "type": dict,
                "required": False,
                "schema": {
                    "max_impact_per_action": {"type": (int, float), "required": False},
                    "max_cumulative_impact": {"type": (int, float), "required": False},
                    "high_impact_requires_approval": {"type": bool, "required": False},
                },
            },
            "time_window": {
                "type": dict,
                "required": False,
                "schema": {
                    "engagement_start": {"type": (int, float), "required": False},
                    "engagement_end": {"type": (int, float), "required": False},
                },
            },
        },
    },
    "capabilities": {
        "type": dict,
        "required": False,
        "schema": {
            "kernel_rootkit": {"type": bool, "required": False},
            "uefi_persistence": {"type": bool, "required": False},
            "spi_flash_write": {"type": bool, "required": False},
            "ai_evasion": {"type": bool, "required": False},
            "zero_day_framework": {"type": bool, "required": False},
            "domain_fronting_c2": {"type": bool, "required": False},
            "dead_drop_c2": {"type": bool, "required": False},
            "p2p_c2": {"type": bool, "required": False},
            "cross_platform_implant": {"type": bool, "required": False},
        },
    },
    "c2": {
        "type": dict,
        "required": False,
        "schema": {
            "front_domain": {"type": str, "required": False},
            "real_domain": {"type": str, "required": False},
            "channel": {"type": str, "required": False},
            "implant_id": {"type": str, "required": False},
        },
    },
    "audit": {
        "type": dict,
        "required": False,
        "schema": {
            "log_path": {"type": str, "required": False},
            "cryptographic_chaining": {"type": bool, "required": False},
            "remote_sink": {"type": (str, type(None)), "required": False},
        },
    },
    "stealth": {
        "type": dict,
        "required": False,
        "schema": {
            "ja3_spoofing": {"type": bool, "required": False},
            "anti_forensics": {"type": bool, "required": False},
            "memory_resident": {"type": bool, "required": False},
            "kernel_operations": {"type": bool, "required": False},
            "secure_delete_passes": {"type": int, "required": False},
            "timestomp_reference": {"type": str, "required": False},
            "wipe_free_space": {"type": bool, "required": False},
        },
    },
    "deployment": {
        "type": dict,
        "required": False,
        "schema": {
            "native_only": {"type": bool, "required": False},
            "docker": {"type": bool, "required": False},
        },
    },
}

ALLOWED_TOP_LEVEL = set(SCHEMA.keys())


def validate_config(config: dict[str, Any]) -> list[str]:
    """
    Validate config dict against schema.

    Returns list of error messages (empty if valid).
    """
    errors: list[str] = []

    # Check for unknown top-level keys
    for key in config:
        if key not in ALLOWED_TOP_LEVEL:
            errors.append(f"Unknown top-level config key: '{key}'")

    # Validate each known section
    for section, section_def in SCHEMA.items():
        if section not in config:
            if section_def.get("required", False):
                errors.append(f"Required config section missing: '{section}'")
            continue

        value = config[section]
        expected_type = section_def["type"]

        if not isinstance(value, expected_type):
            errors.append(
                f"Config section '{section}' must be {expected_type.__name__}, got {type(value).__name__}"
            )
            continue

        # Validate nested schema
        nested_schema = section_def.get("schema", {})
        if nested_schema and isinstance(value, dict):
            for nested_key, nested_val in value.items():
                if nested_key not in nested_schema:
                    errors.append(f"Unknown key '{nested_key}' in section '{section}'")
                    continue
                nested_def = nested_schema[nested_key]
                nested_expected = nested_def["type"]
                if not isinstance(nested_val, nested_expected):
                    errors.append(
                        f"Config '{section}.{nested_key}' must be {nested_expected.__name__}, "
                        f"got {type(nested_val).__name__}"
                    )

    return errors


def load_and_validate(path: str | Path) -> dict[str, Any]:
    """Load raphael.yaml and validate it."""
    path = Path(path)

    if not HAS_YAML:
        print("WARNING: PyYAML not installed — cannot parse YAML config", file=sys.stderr)
        return {}

    if not path.exists():
        print(f"WARNING: Config file not found: {path}", file=sys.stderr)
        return {}

    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    # Apply RAPHAEL_ environment variable overrides
    for env_key, env_value in os.environ.items():
        if env_key.startswith("RAPHAEL_"):
            # RAPHAEL_TARGET_HOST -> target.host
            parts = env_key[len("RAPHAEL_"):].lower().split("__")
            if len(parts) >= 2:
                section = parts[0]
                key = parts[1]
                if section in config and isinstance(config[section], dict):
                    # Try to convert to appropriate type
                    try:
                        if env_value.lower() in ("true", "false"):
                            config[section][key] = env_value.lower() == "true"
                        else:
                            config[section][key] = int(env_value)
                    except ValueError:
                        try:
                            config[section][key] = float(env_value)
                        except ValueError:
                            config[section][key] = env_value

    errors = validate_config(config)
    if errors:
        error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ConfigValidationError(error_msg)

    return config


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate raphael.yaml config")
    parser.add_argument("--config", default="configs/raphael.yaml", help="Path to config file")
    args = parser.parse_args()

    try:
        config = load_and_validate(args.config)
        print(f"Configuration valid: {args.config}")
        print(f"Version: {config.get('version', 'unknown')}")
    except ConfigValidationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
