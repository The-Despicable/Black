"""Sync/async bridge: stream an async router's chunks from raphael-ma's sync core.

raphael-ma's orchestrators are synchronous; host frameworks (e.g. Raphael's
``orchestrator.providers.call_model``) are async (aiohttp). This module is
the single adapter boundary between the two worlds — the recommended way
to consolidate to ONE canonical provider implementation:

1. The host implements ONE async streaming function::

       async def stream_model(model, messages, *, temperature, max_tokens) \\
               -> AsyncIterator[str]

2. raphael-ma wraps it in :class:`RouterProvider` (a normal sync
   :class:`~raphael.multiagent.llm.base.Provider`) and registers it for roles::

       from raphael.multiagent.llm.async_bridge import RouterProvider
       provider = RouterProvider(name="raphael", router=my_stream_model)
       registry.provider = ...  # or construct Registry with a factory

The coroutine runs on a dedicated background thread with its own persistent
event loop (``run_coro_sync``), so:

- the CLI's main thread never blocks the loop (there is none on main),
- the same loop is reused for every turn (no per-call loop setup cost),
- the host's aiohttp session/connector can live on that loop.

The bridge preserves raphael-ma-side behaviors that the host router does not
need to know about: thinking-tag stripping and max_tokens defaulting.

---------------------------------------------------------------------------
STREAMING CONTRACT (what a host router may return, and what happens)
---------------------------------------------------------------------------

The router is called exactly once per turn, as::

    out = router(model, messages, temperature=<float>, max_tokens=<int|None>)

where ``messages`` is a plain list of ``{"role", "content"}`` dicts (never
raphael-ma's ChatMessage type). ``out`` may be any of the following, checked in
this order:

1. **An async iterator** (has ``__aiter__`` — typically an async generator,
   i.e. ``async def router(...)`` that ``yield``s): *streamed end-to-end*.
   A pump coroutine iterates it on the bridge loop and pushes each chunk
   into a thread-safe queue; the sync consumer yields every chunk the
   moment it is produced. First-chunk latency equals the router's own
   time-to-first-token; only a few bytes of partial-tag text can be held
   back by the think-stripper (see below). This is the shape Raphael's
   ``call_model`` should map to.
2. **An awaitable** resolving to (1): awaited on the bridge loop (the
   calling thread blocks only until the awaitable resolves), then streamed
   as above.
3. **An awaitable** resolving to ``str`` or ``Iterable[str]``: resolved,
   then emitted chunk-by-chunk.
4. **A plain ``str`` or sync ``Iterable[str]``/generator**: emitted
   chunk-by-chunk on the calling thread.

Chunks must be non-empty strings; empty/None chunks are dropped. Exceptions
raised inside an async router propagate unchanged out of the sync iterator
(they are transported through the queue, not swallowed). If the consumer
stops early (``.close()`` / GeneratorExit / an exception in the caller's
loop), the pump coroutine is cancelled on the bridge loop so the router's
``finally`` blocks run.

THINKING-TAG STRIPPING (``strip_think=True``, the default)
----------------------------------------------------------
Every chunk passes through :class:`_ThinkFilter`, an incremental filter
whose combined output over the whole stream is byte-identical to
``raphael.multiagent.llm.openai_compat.strip_reasoning`` applied to the *concatenated*
raw chunk text — including think blocks (the exact tags compiled in
  ``openai_compat._THINK_OPEN``) split across
chunk boundaries, unclosed blocks (kept verbatim, like the regex), and
leading/trailing whitespace trimming. Set ``strip_think=False`` to pass
chunks through verbatim (the host already strips reasoning, e.g. Raphael
strips ``reasoning_content`` before yielding).
"""
from __future__ import annotations

import asyncio
import inspect
import queue
import threading
from typing import Any, AsyncIterator, Awaitable, Callable, Iterator, List, Optional

from raphael.multiagent.log import get_logger
from raphael.multiagent.llm.base import ChatMessage, Provider

log = get_logger("async_bridge")

Router = Callable[..., "AsyncIterator[str] | Awaitable[Any] | str | Iterable[str]"]

_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_lock = threading.Lock()
_loop_thread: Optional[threading.Thread] = None


def _get_loop() -> asyncio.AbstractEventLoop:
    """The dedicated bridge loop, started lazily on its own thread."""
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None and not _loop.is_closed():
            return _loop
        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(
            target=_loop.run_forever, name="raphael-ma-async-bridge", daemon=True
        )
        _loop_thread.start()
        return _loop


def run_coro_sync(coro: Awaitable):
    """Run a coroutine on the bridge loop and return its result (blocking)."""
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


# ---------------------------------------------------------------------
# async iterator -> sync iterator, chunk by chunk (NO buffering)
# ---------------------------------------------------------------------

_DONE = object()  # end-of-stream sentinel


def _pump_aiter(ait: Any) -> Iterator[str]:
    """Yield chunks from an async iterator as they arrive.

    A pump coroutine iterates ``ait`` on the bridge loop and pushes each
    chunk into an unbounded thread-safe queue; this generator blocks on
    ``q.get()`` only until the NEXT chunk is available, so the consumer sees
    chunks with the router's own pacing. Producer errors are transported
    through the queue and re-raised here unchanged.
    """
    q: "queue.Queue[Any]" = queue.Queue()

    async def _pump() -> None:
        try:
            async for chunk in ait:
                if chunk:
                    q.put(str(chunk))
        except BaseException as exc:  # noqa: BLE001 - transported, re-raised below
            q.put(exc)
            return
        q.put(_DONE)

    fut = asyncio.run_coroutine_threadsafe(_pump(), _get_loop())
    try:
        while True:
            item = q.get()
            if item is _DONE:
                break
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        # consumer stopped early: cancel the pump so the router unwinds
        if not fut.done():
            fut.cancel()


class _AnextOnly:
    """Adapt an object exposing only ``__anext__`` to the async-iter protocol."""

    def __init__(self, obj: Any):
        self._obj = obj

    def __aiter__(self) -> "_AnextOnly":
        return self

    async def __anext__(self):
        return await self._obj.__anext__()


def _stream_router_output(out: Any) -> Iterator[str]:
    """Dispatch a router return value per the contract in the module docstring."""
    if inspect.isawaitable(out):
        out = run_coro_sync(out)
    if hasattr(out, "__aiter__") or hasattr(out, "__anext__"):
        if not hasattr(out, "__aiter__"):
            out = _AnextOnly(out)
        yield from _pump_aiter(out)
        return
    if out is None:
        return
    if isinstance(out, str):
        yield out
        return
    if hasattr(out, "__iter__"):
        for chunk in out:
            if chunk:
                yield str(chunk)
        return
    yield str(out)


def _strip_reasoning_text(text: str) -> str:
    """Batch reference: remove reasoning blocks — same rules as openai_compat.

    Kept as the executable specification that :class:`_ThinkFilter` (the
    streaming twin) reproduces exactly; see the tests.
    """
    from raphael.multiagent.llm.openai_compat import _THINK_OPEN

    return _THINK_OPEN.sub("", text).strip()


class _ThinkFilter:
    """Incremental think-block stripper — the streaming twin of
    ``openai_compat.strip_reasoning``.

    CONTRACT: for ANY sequence of chunks ``c1 .. cn`` (tags may be split at
    arbitrary chunk boundaries)::

        "".join(f.feed(c1), ..., f.feed(cn)) + f.close()
            == strip_reasoning(c1 + ... + cn)

    Semantics inherited from ``openai_compat._THINK_OPEN`` (DOTALL, non-greedy):

    - a *complete* block is removed, content and tags;
    - an *unclosed* open tag is kept verbatim (the regex has
      nothing to match), and re-emitted when the stream ends;
    - leading/trailing whitespace of the final assembled text is trimmed
      (leading whitespace is suppressed until the first non-whitespace
      character; trailing whitespace is held back until more content or
      stream end).

    ``feed()`` returns only text that is certain to survive; a partial tag
    (up to ``len(tag) - 1`` bytes) may be held internally until the next
    chunk resolves it.
    """

    _OPEN = "<" + "think" + ">"  # exactly the open tag of openai_compat._THINK_OPEN
    _CLOSE = "<" + "/" + "think" + ">"  # exactly the close tag of openai_compat._THINK_OPEN

    def __init__(self) -> None:
        self._in_think = False
        self._pending = ""       # unresolved tail (possible partial tag)
        self._suppressed = ""    # content inside an open block (dropped if it closes)
        self._seen_nonws = False
        self._tail_ws = ""       # trailing whitespace held back
        self._closed = False

    # -- public API ----------------------------------------------------
    def feed(self, chunk: str) -> str:
        if self._closed:
            raise RuntimeError("_ThinkFilter already closed")
        out: List[str] = []
        self._pending += chunk
        while self._pending:
            tag = self._CLOSE if self._in_think else self._OPEN
            idx = self._pending.find(tag)
            if idx >= 0:
                before = self._pending[:idx]
                self._pending = self._pending[idx + len(tag):]
                if self._in_think:
                    # block closed: its content is gone for good
                    self._suppressed = ""
                    self._in_think = False
                else:
                    self._in_think = True
                    self._suppressed = ""
                    emitted = self._emit_text(before)
                    if emitted:
                        out.append(emitted)
            else:
                keep = self._suffix_prefix_len(self._pending, tag)
                cut = len(self._pending) - keep
                resolved, self._pending = self._pending[:cut], self._pending[cut:]
                if self._in_think:
                    self._suppressed += resolved
                else:
                    emitted = self._emit_text(resolved)
                    if emitted:
                        out.append(emitted)
                break  # nothing more is resolvable this round
        return "".join(out)

    def close(self) -> str:
        """Flush the filter; returns any final text (may be empty)."""
        if self._closed:
            return ""
        self._closed = True
        if self._in_think:
            # unclosed block: regex semantics keep it verbatim -> replay it
            self._pending = self._OPEN + self._suppressed + self._pending
            self._suppressed = ""
            self._in_think = False
        final, self._pending = self._pending, ""
        return self._emit_text(final)

    # -- internals ------------------------------------------------------
    @staticmethod
    def _suffix_prefix_len(text: str, tag: str) -> int:
        """Longest k < len(tag) with text.endswith(tag[:k]) (0 if none)."""
        for k in range(min(len(text), len(tag) - 1), -1, -1):
            if text.endswith(tag[:k]):
                return k
        return 0

    def _emit_text(self, text: str) -> str:
        """Apply the leading/trailing-whitespace rules of ``.strip()``."""
        if not text:
            return ""
        if not self._seen_nonws:
            text = text.lstrip()
            if not text:
                return ""  # whitespace before any content: dropped
            self._seen_nonws = True
        core = text.rstrip()
        if core:
            out = self._tail_ws + core
            self._tail_ws = text[len(core):]
            return out
        self._tail_ws += text
        return ""


class RouterProvider(Provider):
    """A sync Provider whose stream_chat delegates to an async router.

    The router signature mirrors raphael-ma's Provider.stream_chat, but async::

        async def router(model, messages, temperature=0.7, max_tokens=None)

    See the module docstring for the exact accepted return shapes and the
    streaming/thinking-tag contract. ``messages`` are plain
    ``[{"role": ..., "content": ...}]`` dicts so the host never needs
    raphael-ma's ChatMessage type.
    """

    def __init__(self, name: str, router: Router, strip_think: bool = True):
        super().__init__(name=name, base_url="", api_key=None)
        self.router = router
        self.strip_think = strip_think

    def stream_chat(
        self,
        model: str,
        messages: List[ChatMessage],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        msgs = [m.as_dict() for m in messages]
        effective_max = max_tokens or self.max_tokens
        out = self.router(model, msgs, temperature=temperature, max_tokens=effective_max)

        filt = _ThinkFilter() if self.strip_think else None
        for chunk in _stream_router_output(out):
            text = str(chunk)
            if filt is not None:
                text = filt.feed(text)
                if not text:
                    continue
            elif not text:
                continue
            yield text
        if filt is not None:
            tail = filt.close()
            if tail:
                yield tail

    def list_models(self) -> List[str]:
        return []

    def close(self) -> None:
        """Stop the bridge loop (optional; called by tests)."""
        global _loop
        with _loop_lock:
            if _loop is not None and not _loop.is_closed():
                _loop.call_soon_threadsafe(_loop.stop)
                _loop = None
