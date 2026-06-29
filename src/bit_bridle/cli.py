"""Streaming REPL entry point for bit-bridle."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown

from .agent import Agent
from .config import Config

console = Console()


def _load_dotenv() -> None:
    """Minimal .env loader (KEY=VALUE per line) so we avoid an extra dependency."""
    env_path = Path.cwd() / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _on_text(chunk: str) -> None:
    console.print(chunk, end="", markup=False, highlight=False)


def _on_tool(name: str, args: dict[str, Any]) -> None:
    rendered = json.dumps(args, ensure_ascii=False)
    if len(rendered) > 200:
        rendered = rendered[:200] + "…"
    console.print(f"\n[dim]→ {name}({rendered})[/dim]")


def _on_tool_result(name: str, output: str) -> None:
    preview = output if len(output) <= 500 else output[:500] + "…"
    console.print(f"[dim]{preview}[/dim]\n")


def main() -> None:
    parser = argparse.ArgumentParser(prog="bridle", description="Agentic coding harness for GLM-5.2.")
    parser.add_argument("-w", "--workspace", default=".", help="Workspace root (default: cwd).")
    parser.add_argument("-p", "--prompt", help="Run a single prompt non-interactively and exit.")
    args = parser.parse_args()

    _load_dotenv()
    config = Config.from_env()
    workspace = Path(args.workspace).resolve()

    agent = Agent(config, workspace, _on_text, _on_tool, _on_tool_result)

    console.print(f"[bold cyan]bit-bridle[/bold cyan] · {config.model} @ {config.base_url}")
    console.print(f"[dim]workspace: {workspace}[/dim]\n")

    if args.prompt:
        agent.send(args.prompt)
        console.print()
        return

    console.print("[dim]Type a request, or Ctrl-D / 'exit' to quit.[/dim]\n")
    while True:
        try:
            user_input = console.input("[bold green]› [/bold green]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye[/dim]")
            break
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue
        agent.send(user_input)
        console.print("\n")


if __name__ == "__main__":
    main()
