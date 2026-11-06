"""OpenAI-compatible chat-completions adapter.

Works with: NVIDIA NIM (integrate.api.nvidia.com/v1), Ollama Cloud
(ollama.com/v1), InferX (model.inferx.net/v1), OpenAI, Groq, Together,
OpenRouter, LM Studio, and anything else speaking the /v1/chat/completions
dialect.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Iterator, List, Optional

import requests

from raphael.multiagent.llm.base import ChatMessage, Provider
from raphael.multiagent.log import get_logger

log = get_logger("provider")

_THINK_OPEN = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_reasoning(text: str) -> str:
    """Remove <think>...</think> blocks emitted by reasoning models."""
    return _THINK_OPEN.sub("", text).strip()


class OpenAICompatProvider(Provider):
    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _error_detail(self, resp: requests.Response) -> str:
        try:
            body = resp.json()
            detail = body.get("error") or body.get("detail") or body
            if isinstance(detail, dict):
                detail = detail.get("message") or json.dumps(detail)[:300]
            return f"HTTP {resp.status_code}: {str(detail)[:300]}"
        except ValueError as exc:  # requests' JSONDecodeError subclasses ValueError
            log.debug("error body was not JSON (status %s): %s", resp.status_code, exc)
            return f"HTTP {resp.status_code} (no body)"

    def stream_chat(
        self,
        model: str,
        messages: List[ChatMessage],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": [m.as_dict() for m in messages],
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens or self.max_tokens:
            payload["max_tokens"] = max_tokens or self.max_tokens

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        attempts = max(1, self.retries + 1)
        last_err: Optional[Exception] = None
        for attempt in range(attempts):
            if attempt:
                time.sleep(1.5 * attempt)
            try:
                resp = requests.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    stream=True,
                    timeout=(10, self.timeout),
                )
                if resp.status_code >= 400:
                    # 4xx is deterministic (bad key/model); don't retry 401/403/404
                    if resp.status_code in (400, 401, 403, 404):
                        raise RuntimeError(
                            f"[{self.name}] {model}: {self._error_detail(resp)}"
                        )
                    raise requests.HTTPError(self._error_detail(resp))
                yield from self._parse_sse(resp)
                return
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                last_err = exc
                continue
        raise RuntimeError(f"[{self.name}] failed after {attempts} attempts: {last_err}")

    def _parse_sse(self, resp: requests.Response) -> Iterator[str]:
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            data = raw[5:].strip()
            if data == "[DONE]":
                return
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            # Reasoning models stream the answer inside ``reasoning_content`` and
            # never emit ``content`` (e.g. NVIDIA nemotron-3.5-lightning). Prefer
            # the visible answer when present; otherwise surface the reasoning
            # stream so the reply is not silently empty.
            content = delta.get("content")
            if not content:
                content = delta.get("reasoning_content")
            if content:
                yield strip_reasoning(content)

    def list_models(self) -> List[str]:
        url = f"{self.base_url.rstrip('/')}/models"
        resp = requests.get(url, headers=self._headers(), timeout=(10, 30))
        if resp.status_code >= 400:
            raise RuntimeError(f"[{self.name}] {self._error_detail(resp)}")
        body = resp.json()
        models = body.get("data") or body.get("models") or []
        out = []
        for m in models:
            mid = m.get("id") if isinstance(m, dict) else str(m)
            if mid:
                out.append(mid)
        return sorted(out)
