# bit-bridle

A minimal **agentic coding harness for GLM-5.2**: a tool-using agent loop that
drives GLM-5.2 over any OpenAI-compatible `/chat/completions` endpoint. Python,
installed as the `bridle` console script.

## Layout

```
src/bit_bridle/
  config.py   Env-based config (Config.from_env): endpoint, key, model, temperature, iteration cap.
  client.py   GLMClient — OpenAI-compatible streaming client; assembles tool-call deltas into messages.
  tools.py    5 tools + their JSON schemas. SPECS (sent to model) / IMPLS / execute(). Paths confined to workspace root.
  agent.py    Agent — the loop: model turn → execute tool calls → feed results back → repeat until no tool calls.
  cli.py      Streaming REPL + one-shot (--prompt) entry point; minimal .env loader.
.claude/workflows/dev-loop.js   Self-improvement workflow (see below).
```

## Conventions

- **Provider is GLM/Zhipu, not Anthropic.** Everything talks to an
  OpenAI-compatible endpoint via the `openai` SDK. Do not pull in Anthropic
  client code. A different endpoint is one `GLM_BASE_URL` change — never
  hard-code provider URLs in logic; read them from `Config`.
- **Tools are workspace-confined.** Every file path goes through
  `tools._resolve()`, which refuses escapes outside the workspace root. Keep new
  tools inside this guard, and add both a `SPECS` schema entry and an `IMPLS`
  impl. Tool output is truncated to `MAX_OUTPUT_CHARS` to protect the context
  window — preserve that for new tools.
- **Tool failures return strings, never raise.** `tools.execute` catches and
  returns `Error: ...` so the model can recover; don't let a tool crash the loop.
- **v1 is intentionally minimal.** No approval prompts yet — the agent writes
  files and runs bash autonomously inside `--workspace`. The roadmap (README)
  is the source of truth for what's deliberately deferred.

## Dev setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Requires `ripgrep` (`rg`) on PATH for the `search` tool. Secrets live in `.env`
(git-ignored); `.env.example` is the tracked template. Never commit a real
`GLM_API_KEY`.

## Verifying changes

There is **no automated test suite yet** (adding pytest is a high-value
improvement). Until then, verify by:

- `pip install -e .` succeeds and `bridle --help` works.
- Import smoke: `python3 -c "import bit_bridle.agent, bit_bridle.cli"`.
- Offline tool exercise: write → edit → read → search → run_bash via
  `bit_bridle.tools.execute`, plus the two safety guards (path-escape refused,
  ambiguous `edit_file` refused).

## Self-improvement loop

`.claude/workflows/dev-loop.js` is a checked-in multi-agent workflow that
incrementally improves this harness: **assess** (parallel read-only lenses) →
**triage** (pick disjoint top-K) → **implement** (isolated git worktree per
item) → **validate** (a *different* agent grades against the assessor's
acceptance criteria) → **integrate** (auto-commit only what passed, to `main`).

Design invariant: **no agent grades its own work** — implementer and validator
are always separate instances, and grading criteria originate upstream of the
implementer. Trigger on-demand (e.g. "run the dev-loop workflow"); override
`rounds`, `perRound`, or `lenses` via args.

## Git

- Conventional-commit-style messages.
- `.claude/` is ignored by the user's global gitignore **except**
  `.claude/workflows/` (re-included via a project `.gitignore` exception) — keep
  workflows tracked, leave other local `.claude/` state ignored.
- Commit/push only when asked.
