"""Tool definitions and execution for the coding harness.

Each tool exposes an OpenAI-compatible JSON schema (``SPECS``) sent to the model,
plus a Python implementation (``IMPLS``) the harness runs locally. All file paths
are resolved relative to, and confined within, the workspace root.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

# Hard cap on how much tool output we feed back to the model, to avoid
# blowing the context window on a single noisy command or huge file.
MAX_OUTPUT_CHARS = 30_000


class ToolError(Exception):
    """Raised when a tool cannot complete; the message is returned to the model."""


def _resolve(workspace: Path, path: str) -> Path:
    """Resolve ``path`` inside ``workspace``, refusing escapes via ../ or absolutes."""
    candidate = (workspace / path).resolve()
    workspace = workspace.resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise ToolError(f"Path '{path}' escapes the workspace root.")
    return candidate


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... [truncated, {len(text) - MAX_OUTPUT_CHARS} more chars]"


def read_file(workspace: Path, path: str) -> str:
    target = _resolve(workspace, path)
    if not target.is_file():
        raise ToolError(f"No such file: {path}")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    numbered = "\n".join(f"{i + 1:>6}\t{line}" for i, line in enumerate(lines))
    return _truncate(numbered) or "(empty file)"


def write_file(workspace: Path, path: str, content: str) -> str:
    target = _resolve(workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {path}"


def edit_file(workspace: Path, path: str, old_string: str, new_string: str) -> str:
    target = _resolve(workspace, path)
    if not target.is_file():
        raise ToolError(f"No such file: {path}")
    text = target.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        raise ToolError("old_string not found in file; it must match exactly.")
    if count > 1:
        raise ToolError(f"old_string is not unique ({count} matches); add more context.")
    target.write_text(text.replace(old_string, new_string), encoding="utf-8")
    return f"Edited {path}"


def run_bash(workspace: Path, command: str, timeout: int = 120) -> str:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"Command timed out after {timeout}s.")
    out = proc.stdout + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    out = out.strip() or "(no output)"
    return _truncate(f"[exit {proc.returncode}]\n{out}")


def search(workspace: Path, pattern: str, path: str = ".") -> str:
    root = _resolve(workspace, path)
    try:
        proc = subprocess.run(
            ["rg", "--line-number", "--no-heading", "--color=never", pattern, str(root)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        raise ToolError("ripgrep (rg) is not installed.")
    except subprocess.TimeoutExpired:
        raise ToolError("Search timed out after 60s.")
    if proc.returncode not in (0, 1):  # 1 == no matches, which is fine
        raise ToolError(proc.stderr.strip() or "search failed")
    return _truncate(proc.stdout.strip() or f"No matches for '{pattern}'.")


# --- registry -------------------------------------------------------------

SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file, returned with 1-based line numbers.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path relative to the workspace root."}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the workspace root."},
                    "content": {"type": "string", "description": "Full file content to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace exactly one unique occurrence of old_string with new_string in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the workspace root."},
                    "old_string": {"type": "string", "description": "Exact text to find (must be unique in the file)."},
                    "new_string": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": "Run a shell command in the workspace and return its combined output and exit code.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "The shell command to execute."}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search file contents with ripgrep and return matching lines with file:line.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression to search for."},
                    "path": {"type": "string", "description": "Directory or file to search (default: workspace root)."},
                },
                "required": ["pattern"],
            },
        },
    },
]

IMPLS: dict[str, Callable[..., str]] = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "run_bash": run_bash,
    "search": search,
}


def execute(workspace: Path, name: str, arguments: dict[str, Any]) -> str:
    impl = IMPLS.get(name)
    if impl is None:
        return f"Error: unknown tool '{name}'."
    try:
        return impl(workspace, **arguments)
    except ToolError as exc:
        return f"Error: {exc}"
    except TypeError as exc:
        return f"Error: bad arguments for {name}: {exc}"
    except Exception as exc:  # noqa: BLE001 - surface failures to the model, don't crash the loop
        return f"Error: {name} failed: {exc}"
