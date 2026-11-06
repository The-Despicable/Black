"""Configuration loading and validation.

The config file lives at <home>/config.yaml (~/.raphael/ma/config.yaml by default).
All provider entries are OpenAI-compatible endpoints. The three the user owns
(nvidia, ollama-cloud, inferx) are enabled; others are placeholders for later.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from raphael.multiagent.paths import config_path, ensure_home, home_from_config

# ---------------------------------------------------------------- defaults

DEFAULT_PROVIDERS: Dict[str, Dict[str, Any]] = {
    # ---- live: the APIs you have today ----
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key_env": "NVIDIA_API_KEY",
        "enabled": True,
        "models": [
            "meta/llama-3.3-70b-instruct",
            "deepseek-ai/deepseek-r1",
            "nvidia/llama-3.1-nemotron-70b-instruct",
        ],
    },
    "ollama-cloud": {
        "base_url": "https://ollama.com/v1",
        "api_key_env": "OLLAMA_API_KEY",
        "enabled": True,
        "models": ["gpt-oss:120b", "deepseek-v3.1:671b", "qwen3-coder:480b", "gemma4:31b"],
    },
    "inferx": {
        "base_url": "https://model.inferx.net/v1",
        "api_key_env": "INFERX_API_KEY",
        "enabled": True,
        "models": ["glm-5.3", "kimi-k3", "qwen3.8-max", "deepseek-v4-flash-0731", "gpt-oss-20b"],
    },
    # ---- future: flip enabled + set env var when you get keys ----
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "enabled": False,
        "models": ["gpt-4o", "gpt-4o-mini", "o4-mini"],
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "enabled": False,
        "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "api_key_env": "TOGETHER_API_KEY",
        "enabled": False,
        "models": ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "enabled": False,
        "models": ["anthropic/claude-sonnet-4", "google/gemini-2.5-pro"],
    },
    "lm-studio": {
        "base_url": "http://localhost:1234/v1",
        "api_key_env": "LMSTUDIO_API_KEY",
        "enabled": False,
        "models": [],
    },
}

# role -> {provider, model}; the genome/evolver may rewrite these later.
DEFAULT_ROLES: Dict[str, Dict[str, str]] = {
    "pro": {"provider": "nvidia", "model": "meta/llama-3.3-70b-instruct"},
    "con": {"provider": "ollama-cloud", "model": "gpt-oss:120b"},
    "judge": {"provider": "inferx", "model": "glm-5.3"},
    "moderator": {"provider": "inferx", "model": "qwen3.8-max"},
    "researcher": {"provider": "nvidia", "model": "deepseek-ai/deepseek-r1"},
    "analyst": {"provider": "ollama-cloud", "model": "deepseek-v3.1:671b"},
    "critic": {"provider": "nvidia", "model": "nvidia/llama-3.1-nemotron-70b-instruct"},
    "integrator": {"provider": "inferx", "model": "kimi-k3"},
    "reflector": {"provider": "inferx", "model": "deepseek-v4-flash-0731"},
    "evolver": {"provider": "nvidia", "model": "deepseek-ai/deepseek-r1"},
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "mode": "mock",  # mock | live
    "providers": DEFAULT_PROVIDERS,
    "roles": DEFAULT_ROLES,
    "memory": {"injection": True, "top_k": 3, "max_insights": 500},
    "evolve": {"enabled": True, "eval_sessions": 5, "min_sessions": 3},
    "governance": {
        # NOTE: 'strict' is deliberately NOT part of this merge base. In the
        # merged config an ABSENT 'strict' means STRICT (fail closed): an
        # empty governance section raises GovernanceConfigError instead of
        # silently allowing. Only an explicit 'strict: false' (which the
        # out-of-box template below writes for standalone use) enables
        # allow-mode. Host deployments therefore get strict-by-default
        # semantics for free: configure audit_path/kill_switch or fail.
        "audit_path": "",
        "kill_switch": "",
        "tool_name": "raphael-ma",  # provenance: "tool": <name> on audit records
    },
    "debate": {"rounds": 3},
    "community": {"agents": 4, "rounds": 2},
    "teams": {"internal_rounds": 1},
    "transcripts": {"dir": "./transcripts"},
    "request": {"timeout_s": 240, "max_tokens": 1200, "retries": 2},
}


@dataclass
class RoleBinding:
    provider: str
    model: str


@dataclass
class Config:
    raw: Dict[str, Any]
    home: Path

    # -- basic accessors -------------------------------------------------
    @property
    def mode(self) -> str:
        return str(self.raw.get("mode", "mock"))

    def with_mode(self, mode: str) -> "Config":
        """A copy of this config pinned to `mode` (never mutates the original)."""
        return Config(raw={**self.raw, "mode": str(mode)}, home=self.home)

    def masked(self) -> Dict[str, Any]:
        """A deep copy of raw with secret-looking values replaced by '***'.

        Keys ending in `_env` / `-env` hold environment variable NAMES, not
        secrets, and are left visible. Use this whenever config is displayed.
        """
        return _mask_secrets(self.raw)


    @property
    def memory(self) -> Dict[str, Any]:
        return dict(self.raw.get("memory") or {})

    @property
    def evolve_cfg(self) -> Dict[str, Any]:
        return dict(self.raw.get("evolve") or {})

    @property
    def governance_cfg(self) -> Dict[str, Any]:
        return dict(self.raw.get("governance") or {})

    def providers(self, only_enabled: bool = False) -> Dict[str, Dict[str, Any]]:
        provs = self.raw.get("providers") or {}
        if only_enabled:
            return {k: v for k, v in provs.items() if v.get("enabled", False)}
        return provs

    def role_binding(self, role: str) -> RoleBinding:
        roles = self.raw.get("roles") or {}
        entry = roles.get(role)
        if isinstance(entry, dict) and entry.get("provider"):
            return RoleBinding(str(entry["provider"]), str(entry.get("model", "")))
        # fallback: first enabled provider that lists models
        for name, prov in self.providers(only_enabled=True).items():
            models = prov.get("models") or []
            if models:
                return RoleBinding(name, str(models[0]))
        return RoleBinding("mock", "mock-default")

    def role_persona(self, role: str) -> Optional[str]:
        """A role may pin a persona name (defaults to the role itself)."""
        roles = self.raw.get("roles") or {}
        entry = roles.get(role)
        if isinstance(entry, dict) and entry.get("persona"):
            return str(entry["persona"])
        return None

    def strategy_param(self, key: str, default: Any) -> Any:
        for section, params in (self.raw or {}).items():
            if isinstance(params, dict) and key in params:
                return params[key]
        return default

    def api_key(self, provider_name: str) -> Optional[str]:
        prov = (self.raw.get("providers") or {}).get(provider_name) or {}
        env_name = prov.get("api_key_env") or f"{provider_name.upper()}_API_KEY"
        val = os.environ.get(env_name, "")
        return val or None


_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")

# Keys that look like they hold credentials. `api_key_env` & friends are
# excluded separately (they name an env var, they do not hold a secret).
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|token|secret|password|passphrase|credential|authorization|auth)",
    re.IGNORECASE,
)
_ENV_NAME_SUFFIXES = ("_env", "-env", "_ENV")


def _mask_secrets(node: Any) -> Any:
    """Recursively replace secret-looking string values with '***'."""
    if isinstance(node, dict):
        out: Dict[str, Any] = {}
        for k, v in node.items():
            key = str(k)
            if (
                isinstance(v, str)
                and v
                and _SECRET_KEY_RE.search(key)
                and not key.endswith(_ENV_NAME_SUFFIXES)
            ):
                out[k] = "***"
            else:
                out[k] = _mask_secrets(v)
        return out
    if isinstance(node, list):
        return [_mask_secrets(v) for v in node]
    return node


def _expand_env(node: Any) -> Any:
    """Expand ${VAR} in string values; leave missing vars as None markers."""
    if isinstance(node, dict):
        return {k: _expand_env(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand_env(v) for v in node]
    if isinstance(node, str):
        def repl(m: re.Match) -> str:
            return os.environ.get(m.group(1), m.group(0))
        return _ENV_PATTERN.sub(repl, node)
    return node


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


_GOVERNANCE_COMMENTS = """\
# ---- governance (fail-closed by default) ----
# strict: ABSENT or true -> an empty governance section is a configuration
#   ERROR (exit code 4): nothing is silently allowed. Host deployments
#   (e.g. Raphael) should leave strict on and configure audit_path and/or
#   kill_switch below.
# strict: false -> EXPLICIT standalone mode: allow everything, debug-log
#   events only. This template sets it so a fresh install works offline.
# audit_path: JSONL audit trail for every session/round/evolution event
#   (Raphael convention: "logs/harness_audit.jsonl"). "" = no audit file.
# kill_switch: "module:attr" import spec -> callable() -> True aborts the
#   session with exit code 3 (fail closed). "" = no kill switch.
# tool_name: provenance stamped on every audit record ("tool": <name>) so
#   a host can emit "raphael" / "raphael.ma" with the same schema.
"""


def write_default_config(home: Path) -> Path:
    """Write the out-of-box config template.

    The governance section is written with ``strict: false`` (explicit, so
    standalone raphael-ma works out of the box) and explanatory comments; the
    merge base ``DEFAULT_CONFIG`` deliberately omits ``strict`` so any
    config that does not carry an explicit ``strict: false`` fails closed
    on an empty governance section.
    """
    ensure_home(home)
    path = config_path(home)
    config = dict(DEFAULT_CONFIG)
    config["governance"] = {"strict": False, **DEFAULT_CONFIG["governance"]}
    text = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    text = text.replace("governance:\n", _GOVERNANCE_COMMENTS + "governance:\n", 1)
    path.write_text(text)
    return path


def update_role_bindings(config_file: Path, role_updates: Dict[str, Dict[str, str]]) -> None:
    """Bind roles to provider/model pairs directly in ``config.yaml``.

    Line-level surgery, NOT a YAML round-trip: comments, blank lines and
    key order elsewhere in the file survive untouched (the governance block
    carries explanatory comments that must not be silently lost).

    ``role_updates`` maps role name → {"provider": ..., "model": ...}.
    """
    try:
        text = config_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"config not found: {config_file}")

    lines = text.split("\n")
    roles_idx = next((i for i, ln in enumerate(lines) if re.match(r"^roles:\s*$", ln)), None)
    if roles_idx is None:
        # no roles section: append one at the end
        lines.append("roles:")
        roles_idx = len(lines) - 1
        for role, binding in role_updates.items():
            lines.append(f"  {role}:")
            lines.append(f"    provider: {binding['provider']}")
            lines.append(f"    model: {binding['model']}")
        config_file.write_text("\n".join(lines), encoding="utf-8")
        return

    # region = role blocks between "roles:" and the next top-level key
    end_idx = next(
        (i for i in range(roles_idx + 1, len(lines)) if lines[i] and not lines[i].startswith((" ", "\t", "#"))),
        len(lines),
    )

    for role, binding in role_updates.items():
        # locate the role's block inside the region
        block_start = None
        for i in range(roles_idx + 1, end_idx):
            if re.match(rf"^  {re.escape(role)}:\s*$", lines[i]):
                block_start = i
                break
        if block_start is None:
            insert_at = end_idx if not lines[end_idx - 1].strip() else end_idx
            new_block = [
                f"  {role}:",
                f"    provider: {binding['provider']}",
                f"    model: {binding['model']}",
                "",
            ]
            lines[insert_at:insert_at] = new_block
            roles_idx += 0  # header unchanged; region grew after it
            end_idx += len(new_block)
            continue
        # find block end (next two-space key or region end)
        block_end = next(
            (
                i
                for i in range(block_start + 1, end_idx)
                if re.match(r"^  \S", lines[i])
            ),
            end_idx,
        )
        wrote_provider = wrote_model = False
        for i in range(block_start + 1, block_end):
            if re.match(r"^    provider:\s*", lines[i]):
                lines[i] = f"    provider: {binding['provider']}"
                wrote_provider = True
            elif re.match(r"^    model:\s*", lines[i]):
                lines[i] = f"    model: {binding['model']}"
                wrote_model = True
        if not wrote_provider or not wrote_model:
            additions: List[str] = []
            if not wrote_provider:
                additions.append(f"    provider: {binding['provider']}")
            if not wrote_model:
                additions.append(f"    model: {binding['model']}")
            lines[block_start + 1:block_start + 1] = additions
            end_idx += len(additions)

    config_file.write_text("\n".join(lines), encoding="utf-8")


def load_dotenv(home: Optional[Path] = None) -> None:
    """Load simple KEY=VALUE overrides from ``.env`` files without a dependency.

    Existing process environment always wins; this is a development convenience,
    never a secret-storage layer.
    """
    candidates = [Path(".env")]
    if home is not None:
        candidates.append(Path(home) / ".env")
    # Search upwards a couple of levels so 'raphael-ma doctor' works from project dirs.
    current = Path.cwd()
    for _ in range(3):
        candidates.append(current / ".env")
        current = current.parent
    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except Exception:
            continue
        if not candidate.is_file():
            continue
        try:
            for raw in candidate.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip(chr(34)+chr(39)).strip()
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            continue


def load_config(home: Optional[Path] = None) -> Config:
    """Load config, merging user file over defaults. Missing file -> defaults."""
    if home is None:
        home = home_from_config(None)
    path = config_path(home)
    user_cfg: Dict[str, Any] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text()) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Config at {path} must be a YAML mapping")
        user_cfg = _expand_env(loaded)
        # home may be re-pinned inside the config itself
        cfg_home = user_cfg.get("home")
        if cfg_home and home is None:
            home = Path(str(cfg_home)).expanduser().resolve()
    merged = _deep_merge(DEFAULT_CONFIG, user_cfg)
    merged.pop("home", None)  # avoid echo when re-dumping
    return Config(raw=merged, home=home)
