"""Thin wrapper over the OpenAI-compatible GLM endpoint with streaming."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from openai import OpenAI

from .config import Config


@dataclass
class StreamResult:
    """The assistant message assembled from a streamed response."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def to_message(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or None}
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        return msg


class GLMClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._client = OpenAI(api_key=config.api_key, base_url=config.base_url)

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_text: callable,
    ) -> StreamResult:
        """Stream one assistant turn.

        ``on_text`` is called with each text chunk as it arrives. Tool-call
        deltas are accumulated by index into complete call objects.
        """
        result = StreamResult()
        # index -> partial tool call (id, name, accumulated argument string)
        partial: dict[int, dict[str, Any]] = {}

        stream = self._client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            tools=tools,
            temperature=self.config.temperature,
            stream=True,
        )

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                result.content += delta.content
                on_text(delta.content)

            for tc in delta.tool_calls or []:
                slot = partial.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    slot["args"] += tc.function.arguments

        for index in sorted(partial):
            slot = partial[index]
            result.tool_calls.append(
                {
                    "id": slot["id"],
                    "type": "function",
                    "function": {"name": slot["name"], "arguments": slot["args"] or "{}"},
                }
            )
        return result
