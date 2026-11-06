"""Provider abstraction for raphael-ma."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

# Fallback score when a judge/moderator omits a participant score or emits a
# non-numeric one. Shared by the mock engine (which fabricates judge output)
# and the orchestrators (which consume it) so both stay in sync.
DEFAULT_SCORE = 6.5


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str

    def as_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class Provider:
    """A chat-completion provider. All live providers are OpenAI-compatible."""
    name: str
    base_url: str
    api_key: Optional[str]
    models: List[str] = field(default_factory=list)
    timeout: float = 240.0
    retries: int = 2
    max_tokens: int = 1200

    def stream_chat(
        self,
        model: str,
        messages: List[ChatMessage],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        raise NotImplementedError

    def list_models(self) -> List[str]:
        raise NotImplementedError
