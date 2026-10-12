"""Embeddings and fact extraction through Bedrock or an OpenAI-compatible API, plus prompts."""

import asyncio
import json
from collections.abc import Sequence
from typing import Any, Protocol

import boto3
import httpx

from dash.config import Settings
from dash.db import EMBED_DIM

# Below this cosine distance a new fact counts as a repeat of a stored one.
DUPLICATE_DISTANCE = 0.08
# Above this the memory is not relevant enough to put in the prompt.
RELEVANT_DISTANCE = 0.65

EXTRACT_PROMPT = """You maintain long-term memory for a personal assistant.
Read the exchange below. List the durable facts about the user that are worth \
remembering in future conversations: preferences, people, projects, plans, accounts, \
decisions. Skip small talk, one-off requests, and anything already obvious.
Write each fact as one short standalone sentence in the third person ("The user ...").
Answer with only a JSON array of strings. Answer [] if there is nothing to keep.

<user>
{user}
</user>
<assistant>
{assistant}
</assistant>"""


class Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class Extractor(Protocol):
    async def extract(self, user: str, assistant: str) -> list[str]: ...


def parse_facts(text: str) -> list[str]:
    """Pull the JSON array out of a model reply. Anything malformed means no facts."""
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end < start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item.strip() for item in data if isinstance(item, str) and item.strip()]  # pyright: ignore[reportUnknownVariableType]


def system_prompt(memories: Sequence[str]) -> str | None:
    if not memories:
        return None
    lines = "\n".join(f"- {m}" for m in memories)
    return (
        "Things you remember about the user from earlier conversations. "
        "Use them when relevant. Do not mention this list unless asked.\n" + lines
    )


class Bedrock:
    def __init__(self, embed_model: str, extract_model: str) -> None:
        # Credentials and region come from the standard AWS env chain (hermes-bedrock secret).
        self._client: Any = boto3.client("bedrock-runtime")  # pyright: ignore[reportUnknownMemberType]
        self._embed_model = embed_model
        self._extract_model = extract_model

    async def embed(self, text: str) -> list[float]:
        body = json.dumps({"inputText": text[:20000], "normalize": True})
        response = await asyncio.to_thread(
            self._client.invoke_model, modelId=self._embed_model, body=body
        )
        return list(json.loads(response["body"].read())["embedding"])

    async def extract(self, user: str, assistant: str) -> list[str]:
        prompt = EXTRACT_PROMPT.format(user=user[:8000], assistant=assistant[:8000])
        response = await asyncio.to_thread(
            self._client.converse,
            modelId=self._extract_model,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 512, "temperature": 0},
        )
        parts = response["output"]["message"]["content"]
        return parse_facts("".join(p.get("text", "") for p in parts))

    async def close(self) -> None:
        self._client.close()


class OpenAICompatible:
    """Embeddings and fact extraction through any OpenAI-compatible API (LiteLLM, OpenRouter)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        embed_model: str,
        extract_model: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url, headers=headers, timeout=60, transport=transport
        )
        self._embed_model = embed_model
        self._extract_model = extract_model

    async def embed(self, text: str) -> list[float]:
        body = {"model": self._embed_model, "input": text[:20000], "dimensions": EMBED_DIM}
        response = await self._client.post("/embeddings", json=body)
        response.raise_for_status()
        return list(response.json()["data"][0]["embedding"])

    async def extract(self, user: str, assistant: str) -> list[str]:
        prompt = EXTRACT_PROMPT.format(user=user[:8000], assistant=assistant[:8000])
        body = {
            "model": self._extract_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 512,
            "temperature": 0,
        }
        response = await self._client.post("/chat/completions", json=body)
        response.raise_for_status()
        return parse_facts(response.json()["choices"][0]["message"]["content"] or "")

    async def close(self) -> None:
        await self._client.aclose()


def memory_models(settings: Settings) -> Bedrock | OpenAICompatible:
    """Return the OpenAI-compatible client if MEMORY_BASE_URL is set, else Bedrock."""
    if settings.memory_base_url:
        return OpenAICompatible(
            settings.memory_base_url,
            settings.memory_api_key,
            settings.embed_model,
            settings.extract_model,
        )
    return Bedrock(settings.embed_model, settings.extract_model)
