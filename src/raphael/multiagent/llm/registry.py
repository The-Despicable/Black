"""Provider registry: resolves roles to concrete provider+model pairs.

Hosts with their own model routing (e.g. Raphael's async ``call_model``)
inject it via ``Registry(cfg, factory=...)``: the factory is asked first
for every provider name and may return a custom :class:`Provider` (see
``raphael.multiagent.llm.async_bridge.RouterProvider``); returning None falls back to
raphael-ma's built-in OpenAI-compatible adapter.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from raphael.multiagent.config import Config, RoleBinding
from raphael.multiagent.llm.base import Provider
from raphael.multiagent.llm.mock import MockProvider
from raphael.multiagent.llm.openai_compat import OpenAICompatProvider

ProviderFactory = Callable[[Config, str], Optional[Provider]]


def build_provider(cfg: Config, name: str, force_mock: bool = False) -> Provider:
    if force_mock or cfg.mode == "mock" or name == "mock":
        return MockProvider()
    prov = (cfg.raw.get("providers") or {}).get(name)
    if not prov:
        raise KeyError(
            f"provider '{name}' is not defined in config.yaml. "
            f"Known: {', '.join((cfg.providers() or {}).keys()) or 'none'}"
        )
    return OpenAICompatProvider(
        name=name,
        base_url=str(prov.get("base_url", "")),
        api_key=cfg.api_key(name),
        models=[str(m) for m in (prov.get("models") or [])],
        timeout=float((cfg.raw.get("request") or {}).get("timeout_s", 240)),
        retries=int((cfg.raw.get("request") or {}).get("retries", 2)),
        max_tokens=int((cfg.raw.get("request") or {}).get("max_tokens", 1200)),
    )


class Registry:
    def __init__(self, cfg: Config, factory: Optional[ProviderFactory] = None):
        self.cfg = cfg
        self.factory = factory
        self._cache: Dict[str, Provider] = {}

    def provider(self, name: str) -> Provider:
        if name not in self._cache:
            custom = self.factory(self.cfg, name) if self.factory else None
            self._cache[name] = custom or build_provider(self.cfg, name)
        return self._cache[name]

    def binding(self, role: str) -> RoleBinding:
        return self.cfg.role_binding(role)

    def resolve(self, role: str) -> Provider:
        binding = self.binding(role)
        return self.provider(binding.provider)

    def live_providers_with_keys(self) -> List[str]:
        out = []
        for name in (self.cfg.providers(only_enabled=True) or {}):
            if self.cfg.api_key(name):
                out.append(name)
        return out
