# Codex + oMLX + Claude Pro bridge

A Python stdio MCP bridge for bounded, **read-only** coding subtasks in the Codex desktop app. Codex remains the OpenAI coordinator: it reads the repository, edits files, runs tests, and checks results. `smart_models.delegate_readonly` routes small Python functions, docstrings, type hints, and test ideas to a local oMLX model; deeper design, concurrency, performance, and subtle bug analysis go to Claude Code using an active Claude Pro/Max **subscription login**. A Claude usage-limit response triggers a SQLite-backed cooldown and fallback to oMLX. If both providers are unavailable, the tool returns control to Codex.

This is task-level delegation, not a replacement for the Codex main model or a way to share a single inference across three providers. Model suggestions have no filesystem access through this bridge and require Codex review. The router uses heuristics and observed latency; it cannot read subscription quota ahead of time or guarantee a particular provider's quality.

## Requirements

- macOS with the Codex desktop app and Python 3.9+ (standard library only).
- [oMLX](https://github.com/jundot/omlx) installed with a working managed server and a locally installed coding model. The default model is `mlx-community/Qwen2.5-Coder-7B-Instruct-8bit`; set `OMLX_MODEL` to another installed model when needed. oMLX settings live outside this repository at `~/.omlx/settings.json`.
- Claude Code CLI installed, with a **Claude Pro or Max subscription** login. Run `claude auth login --claudeai`, then `claude auth status --json`. The bridge refuses an API-key authentication path and strips `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, and `ANTHROPIC_BASE_URL` from child process environments. It does not switch to API billing.
- An OpenAI/Codex login for the Codex app. The bridge does not contain or need OpenAI API credentials.

Check binary locations with `command -v claude` and `command -v omlx`. On the Mac used for the original setup they were `~/.local/bin/claude` and `/opt/homebrew/bin/omlx`; these are **examples**, not hardcoded repository paths. Verify the local endpoint with `omlx status` and a model request before relying on routing. The oMLX bridge reads its local port and authentication value at runtime from oMLX settings; never copy that settings file into this repository.

## Install in Codex

Clone this repository to a stable location. Add the following to `~/.codex/config.toml`, replacing `/absolute/path/to/repo` and binary paths with your machine's paths. Merge these tables with existing config rather than overwriting the file. `SMART_MODELS_DB` points to local state outside the checkout; its parent directory is created automatically.

```toml
[mcp_servers.smart_models]
command = "/usr/bin/python3"
args = ["/absolute/path/to/repo/smart_model_router_mcp.py"]
tool_timeout_sec = 210

[mcp_servers.smart_models.env]
CLAUDE_BIN = "/absolute/path/to/claude"
OMLX_BIN = "/absolute/path/to/omlx"
SMART_MODELS_DB = "/absolute/path/to/private/state.sqlite3"
OMLX_MODEL = "mlx-community/Qwen2.5-Coder-7B-Instruct-8bit"
```

Only `smart_models` is needed for automatic routing. To expose the direct provider tools as well, add these optional entries (the same binary environment can be set per server):

```toml
[mcp_servers.omlx_local]
command = "/usr/bin/python3"
args = ["/absolute/path/to/repo/omlx_mcp.py"]

[mcp_servers.claude_pro]
command = "/usr/bin/python3"
args = ["/absolute/path/to/repo/claude_subscription_mcp.py"]
```

For consistent use in coding tasks, add [the example policy](AGENTS.example.md) to your global `~/.codex/AGENTS.md` (append it to existing instructions, adapting paths and preferences). Restart the Codex app or create a new task so it reloads MCP server registration. Existing tasks may retain an older tool catalog.

## Routing and state

`delegate_readonly` takes a self-contained `prompt` (up to 12,000 characters), optional `kind` (`snippet`, `docs`, `tests`, `explain`, `architecture`, `deep_review`, `complex_debug`, `performance`, `security`, or `auto`), `mode` (`auto`, `fast`, `deep`, `local_only`), and `privacy` (`standard` or `local_only`). `fast` prefers oMLX; `deep` prefers Claude and falls back to oMLX; `local_only` never calls Claude. Sensitive-looking text is routed locally, though callers should avoid passing secrets entirely. Local-first failures return control to Codex without consuming Claude capacity. Deep Claude quota failures fall back to oMLX.

`routing_status` reports counters, last-day outcomes, latency estimates, and cooldown. Set `probe=true` to check Claude subscription auth, the oMLX endpoint, and whether the configured model directory exists without making an inference call. An oMLX connection refusal attempts to start its managed server once before retrying. Claude limit failures back off for one hour, then progressively longer up to six hours on repeated failures; this is **not** the exact reset time. After cooldown, a deep task retries Claude automatically.

SQLite uses WAL and atomic writes to share state between MCP processes. It stores provider names, counts, timings, bounded outcome categories, and cooldowns with up to 5,000 history rows. It does **not** store prompts, answers, credentials, or repository content. Keep the database outside Git; `.gitignore` excludes common local state. The service still passes the bounded prompt to its selected provider, so use `privacy="local_only"` or avoid delegation for sensitive work.

## Verify and troubleshoot

Run `python3 -m unittest discover -s tests -p 'test_*.py' -v` in this checkout. In a fresh Codex task, ask Codex to invoke `smart_models.routing_status` with `probe=true`, then try one small Python docstring request and one deeper Python concurrency analysis. The status call only checks authentication and health; a successful inference test verifies the actual provider path. If Claude is at its session or weekly limit, the deeper call should report an oMLX fallback and a Claude cooldown; retry occurs after cooldown. If the model's oMLX `/v1/models` list exposes an alias instead of the model's filesystem name, `omlx_model_installed` checks the installed directory separately.

If Claude reports an API-key source, remove any API-key overrides from its *local* configuration and sign in with `claude auth login --claudeai`. Do not paste tokens into GitHub issues. If oMLX is unavailable, check the server, local model, `OMLX_BIN`, and the port in `~/.omlx/settings.json`. If no MCP tool appears in Codex, verify the absolute script path, Python path, TOML syntax, and restart the app/new task. All tool calls are read-only model work; Codex can continue without the bridge.

## Files

- `smart_model_router_mcp.py`: stdio JSON-RPC MCP endpoint with `delegate_readonly` and `routing_status`.
- `routing_core.py`: task classification, SQLite metrics and cooldown, provider fallback.
- `claude_subscription_mcp.py`: subscription-only Claude Code invocation and optional direct MCP tool.
- `omlx_mcp.py`: local Responses client, managed-server recovery, optional direct MCP tool.
- `tests/`: billing guard, routing, privacy, quota, persistence, and local recovery tests.

The example config and this repository contain no live credentials. Keep `~/.claude`, `~/.omlx`, `~/.codex`, your local SQLite state, and environment files private.
