"""OpenAI-compatible streaming client for the hermes router."""

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

Kind = Literal["text", "reasoning", "tool", "status"]

CUSTOM_EVENTS: dict[str, Kind] = {"hermes.tool.progress": "tool", "hermes.status": "status"}


@dataclass(frozen=True)
class Delta:
    """One piece of a streamed hermes turn: answer text, reasoning text, or a tool/status update."""

    kind: Kind
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def parse_sse_frame(event: str | None, payload: str) -> list[Delta]:
    """Return the deltas carried by one SSE frame."""
    payload = payload.strip()
    if not payload or payload == "[DONE]":
        return []
    chunk: dict[str, Any] = json.loads(payload)
    if event in CUSTOM_EVENTS:
        return [Delta(CUSTOM_EVENTS[event], data=chunk)]
    if event:
        return []
    choices: list[dict[str, Any]] = chunk.get("choices") or []
    if not choices:
        return []
    delta: dict[str, Any] = choices[0].get("delta") or {}
    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
    content = delta.get("content")
    return [
        *([Delta("reasoning", reasoning)] if isinstance(reasoning, str) and reasoning else []),
        *([Delta("text", content)] if content else []),
    ]


class Hermes:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url, headers=headers, timeout=httpx.Timeout(900, connect=10)
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def stream(self, messages: Sequence[Mapping[str, str]]) -> AsyncIterator[Delta]:
        """Yield each text, reasoning, tool and status delta of one hermes turn."""
        body = {"model": self.model, "messages": list(messages), "stream": True}
        async with self._client.stream("POST", "/chat/completions", json=body) as response:
            response.raise_for_status()
            event: str | None = None
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event = line.removeprefix("event:").strip()
                elif line.startswith("data:"):
                    for delta in parse_sse_frame(event, line.removeprefix("data:")):
                        yield delta
                elif not line:
                    event = None
