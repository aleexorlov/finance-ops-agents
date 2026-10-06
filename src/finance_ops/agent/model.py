"""The model side of the loop: a small protocol, and the Claude implementation."""

from typing import Any, Protocol

from finance_ops.agent.types import ModelTurn, TokenUsage, ToolCall, ToolSpec

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_BASE_URL = "https://api.anthropic.com"
MAX_OUTPUT_TOKENS = 1024


class ModelError(Exception):
    """The model API failed or returned something the loop cannot use."""


class ModelClient(Protocol):
    async def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec]
    ) -> ModelTurn: ...


class ClaudeModel:
    """Claude via the Messages API.

    The base URL is always passed explicitly so the client never picks up an
    ANTHROPIC_BASE_URL meant for some other tool in the same shell.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL):
        from anthropic import AsyncAnthropic

        self.model = model
        self._client = AsyncAnthropic(api_key=api_key, base_url=base_url, max_retries=2)

    async def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec]
    ) -> ModelTurn:
        import anthropic

        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                # Caching the system prompt also caches the tool definitions before it.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=[
                    {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                    for t in tools
                ],
                messages=messages,
            )
        except anthropic.APIError as exc:
            raise ModelError(f"{type(exc).__name__}: {exc}") from exc
        return _to_turn(response)


def _to_turn(response: Any) -> ModelTurn:
    texts, calls, content = [], [], []
    for block in response.content:
        if block.type == "text":
            texts.append(block.text)
            content.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input)))
            content.append(
                {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
            )
    usage = response.usage
    return ModelTurn(
        text="\n".join(texts).strip(),
        tool_calls=tuple(calls),
        stop_reason=response.stop_reason or "unknown",
        usage=TokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
        ),
        content=tuple(content),
    )
