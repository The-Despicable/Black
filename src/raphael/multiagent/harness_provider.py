"""Phase 1 seam: bind an agora Registry to Raphael's governed provider routing.

agora's orchestrators expect synchronous :class:`Provider` objects. Raphael's
canonical model call is async (`orchestrator.providers.call_model`). This module
connects the two through :class:`agora.llm.async_bridge.RouterProvider` so that:

- resolver/prefix logic, retries, and token stripping stay in agora's adapter,
- routed text still passes through agora's governance (`runner.gate`),
- no second prompt/router policy is introduced.

Default usage (ask your host to supply a real async router)::

    from raphael.multiagent.config import load_config
    from raphael.multiagent.harness_provider import build_registry

    cfg = load_config()
    registry = build_registry(cfg, use_raphael_router=True)

If ``use_raphael_router`` is false (or the Raphael router cannot be imported),
the Registry falls back to agora's own adapter configuration.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .config import Config, RoleBinding
from .llm.async_bridge import RouterProvider
from .llm.registry import Registry

log = logging.getLogger(__name__)


async def _raphael_router(model: str, messages: list, temperature: float = 0.7, max_tokens: Optional[int] = None) -> str:
    """Adapter target for :class:`RouterProvider`.

    Raphael's canonical async entry point returns a full string, so this
    adapter is intentionally *full-response* by default. Token-level streaming
    from Raphael into agora is handled by the async_bridge only when the caller
    supplies an async iterator.
    """
    import asyncio

    try:
        from orchestrator.providers import call_model  # type: ignore[import]
    except Exception as exc:  # pragma: no cover - exercised by import failure tests
        raise RuntimeError(f"Raphael provider routing unavailable: {exc}") from exc

    return await call_model(model, messages, max_tokens=(max_tokens or 1200), temperature=temperature)


class ModelUnavailableError(RuntimeError):
    """Raised when neither a host router nor an agora adapter can be built."""


def _wrap_router(provider: Any, strip_think: bool = True) -> RouterProvider:
    return RouterProvider(name="raphael", router=provider, strip_think=strip_think)


def build_registry(
    cfg: Config,
    *,
    async_router: Optional[Callable] = None,
    use_raphael_router: bool = False,
    host_only_live: bool = True,
    strip_think: bool = True,
) -> Registry:
    """Build a Registry, optionally delegating to Raphael's async router.

    If ``use_raphael_router`` is True, the builder uses `_raphael_router`, which
    calls `orchestrator.providers.call_model`. Otherwise we ask callers to provide
    `async_router` or fall back to agora's default adapter.
    """
    if async_router is None and use_raphael_router:
        if not (host_only_live and getattr(cfg, "mode", "") != "live"):
            async_router = _raphael_router

    if async_router is None:

        def factory(_cfg: Config, _name: str) -> Optional[object]:
            return None

        # No host router: keep agora's default adapter/mod mock behavior.
        return Registry(cfg, factory=factory)

    def factory(_cfg: Config, _name: str) -> RouterProvider:
        return RouterProvider(name="raphael", router=async_router, strip_think=strip_think)

    return Registry(cfg, factory=factory)