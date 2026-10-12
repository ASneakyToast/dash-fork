"""A small ACP agent over stdio for the tests. What it does depends on the prompt text."""

import asyncio
import uuid
from typing import Any, cast

from acp import (
    Agent,
    Client,
    plan_entry,
    run_agent,
    start_tool_call,
    text_block,
    tool_content,
    update_agent_message_text,
    update_agent_thought_text,
    update_plan,
    update_tool_call,
)
from acp.schema import (
    AgentCapabilities,
    AllowedOutcome,
    InitializeResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PermissionOption,
    PromptResponse,
    TextContentBlock,
    ToolCallUpdate,
)


class EchoAgent:
    """Echo each prompt, with a thought, a plan and a tool call on the way."""

    def __init__(self) -> None:
        self.client: Client | None = None
        self.sessions: dict[str, list[str]] = {}
        self.cancelled: dict[str, asyncio.Event] = {}

    def on_connect(self, conn: Client) -> None:
        """Keep the connection to the client."""
        self.client = conn

    async def initialize(self, protocol_version: int, **kwargs: Any) -> InitializeResponse:
        """Return the agent's capabilities."""
        return InitializeResponse(
            protocol_version=protocol_version,
            agent_capabilities=AgentCapabilities(load_session=True),
        )

    async def new_session(self, cwd: str, **kwargs: Any) -> NewSessionResponse:
        """Return a new empty session."""
        session_id = uuid.uuid4().hex
        self.sessions[session_id] = []
        return NewSessionResponse(session_id=session_id)

    async def load_session(self, cwd: str, session_id: str, **kwargs: Any) -> LoadSessionResponse:
        """Replay a known session, or raise for one this process never made."""
        if session_id not in self.sessions:
            from acp import RequestError

            raise RequestError.invalid_params({"sessionId": session_id})
        assert self.client is not None
        for said in self.sessions[session_id]:
            await self.client.session_update(session_id, update_agent_message_text(said))
        return LoadSessionResponse()

    async def say(self, session_id: str, text: str) -> None:
        """Send one piece of the reply."""
        assert self.client is not None
        await self.client.session_update(session_id, update_agent_message_text(text))

    async def prompt(self, prompt: list[Any], session_id: str, **kwargs: Any) -> PromptResponse:
        """Answer one prompt."""
        assert self.client is not None
        texts = [b.text for b in prompt if isinstance(b, TextContentBlock)]
        text = texts[-1]
        self.sessions[session_id].append(text)
        await self.client.session_update(session_id, update_agent_thought_text("thinking"))
        await self.client.session_update(session_id, update_plan([plan_entry("echo")]))
        await self.client.session_update(
            session_id, start_tool_call("t1", "Read notes", kind="read", status="in_progress")
        )
        await self.client.session_update(
            session_id,
            update_tool_call("t1", status="completed", content=[tool_content(text_block("notes"))]),
        )
        if "stubborn" in text:
            await asyncio.Event().wait()
        if "slow" in text:
            await self.cancelled.setdefault(session_id, asyncio.Event()).wait()
            await self.say(session_id, "stopped")
            return PromptResponse(stop_reason="cancelled")
        if "permission" in text:
            answer = await self.client.request_permission(
                session_id,
                ToolCallUpdate(tool_call_id="t2", title="Run rm -rf /tmp/x"),
                [
                    PermissionOption(option_id="yes", name="Allow", kind="allow_once"),
                    PermissionOption(option_id="no", name="Deny", kind="reject_once"),
                ],
            )
            allowed = (
                isinstance(answer.outcome, AllowedOutcome) and answer.outcome.option_id == "yes"
            )
            await self.say(session_id, "allowed" if allowed else "denied")
            return PromptResponse(stop_reason="end_turn")
        await self.say(session_id, f"echo {len(self.sessions[session_id])}: ")
        await self.say(session_id, " | ".join(texts))
        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        """Stop the session's running prompt."""
        self.cancelled.setdefault(session_id, asyncio.Event()).set()


if __name__ == "__main__":
    asyncio.run(run_agent(cast("Agent", EchoAgent()), use_unstable_protocol=True))
