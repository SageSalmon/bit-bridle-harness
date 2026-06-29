"""The agent loop: model turn -> tool calls -> tool results -> repeat."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from . import tools
from .client import GLMClient
from .config import Config

SYSTEM_PROMPT = """You are bit-bridle, a coding agent operating inside a user's workspace.

You have tools to read, write, edit, and search files, and to run shell commands.
Work in small, verifiable steps:
- Inspect before you change: read files and search before editing.
- Make targeted edits with edit_file; use write_file only for new files or full rewrites.
- After changing code, run the relevant build/test/lint command to verify it.
- Prefer running commands over guessing. Keep going until the task is done.

When the task is complete, stop calling tools and give a short summary of what you did."""


class Agent:
    def __init__(
        self,
        config: Config,
        workspace: Path,
        on_text: Callable[[str], None],
        on_tool: Callable[[str, dict[str, Any]], None],
        on_tool_result: Callable[[str, str], None],
    ) -> None:
        self.config = config
        self.workspace = workspace
        self.client = GLMClient(config)
        self.on_text = on_text
        self.on_tool = on_tool
        self.on_tool_result = on_tool_result
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def send(self, user_input: str) -> None:
        """Run one user turn to completion, including any tool-call iterations."""
        self.messages.append({"role": "user", "content": user_input})

        for _ in range(self.config.max_tool_iterations):
            result = self.client.stream(self.messages, tools.SPECS, self.on_text)
            self.messages.append(result.to_message())

            if not result.tool_calls:
                return

            for call in result.tool_calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                self.on_tool(name, args)
                output = tools.execute(self.workspace, name, args)
                self.on_tool_result(name, output)
                self.messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": output}
                )

        self.on_text(
            f"\n[stopped after {self.config.max_tool_iterations} tool iterations]\n"
        )
