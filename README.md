# bit-bridle

A minimal agentic coding harness for **GLM-5.2**, talking to any OpenAI-compatible
`/chat/completions` endpoint. It runs a tool-using agent loop with five core tools
(read, write, edit, bash, search) and a streaming REPL.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Requires `ripgrep` (`rg`) on your PATH for the `search` tool.

## Configure

```bash
cp .env.example .env
# edit .env: set GLM_API_KEY, and GLM_BASE_URL for your provider
```

`GLM_BASE_URL` can point at Zhipu, z.ai, or a self-hosted vLLM/SGLang server —
the harness is unchanged across them.

## Run

```bash
# interactive REPL
bridle

# one-shot, in a specific workspace
bridle --workspace ~/code/my-project --prompt "add a --version flag to the CLI"
```

## How it works

```
src/bit_bridle/
  config.py   env-based config (endpoint, key, model, temperature)
  client.py   OpenAI-compatible streaming client; assembles tool-call deltas
  tools.py    5 tools + JSON schemas; paths confined to the workspace root
  agent.py    the loop: model turn → execute tool calls → feed results → repeat
  cli.py      streaming REPL / one-shot entry point
```

The loop runs until the model stops requesting tools or hits
`GLM_MAX_TOOL_ITERATIONS`. All file paths are resolved inside the workspace
root; `read_file`/`run_bash`/`search` output is truncated to keep the context
window bounded.

## Roadmap (v1 is intentionally minimal)

- Permission/approval prompts before writes and shell commands
- Conversation persistence and `/resume`
- Token accounting and context compaction
- MCP tool support
- Parallel tool execution
