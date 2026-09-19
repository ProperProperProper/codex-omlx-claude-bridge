#!/usr/bin/env python3
"""Read-only Claude Code MCP bridge that requires subscription OAuth."""

import json
import os
import subprocess
import sys

CLAUDE = os.environ.get("CLAUDE_BIN", "claude")
SETTINGS = json.dumps({"env": {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": "", "ANTHROPIC_BASE_URL": ""}})


def clean_env():
    env = os.environ.copy()
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        env.pop(key, None)
    return env


def ask(prompt):
    env = clean_env()
    status = subprocess.run(
        [CLAUDE, "--settings", SETTINGS, "auth", "status", "--json"],
        env=env, capture_output=True, text=True, timeout=15,
    )
    try:
        auth = json.loads(status.stdout)
    except ValueError:
        raise RuntimeError("Could not check Claude Code authentication.")
    if not auth.get("loggedIn") or auth.get("authMethod") != "claude.ai" or auth.get("apiKeySource"):
        raise RuntimeError("Claude subscription login is not active. Sign in to Claude Code with your Claude account first.")
    result = subprocess.run(
        [CLAUDE, "--settings", SETTINGS, "--print", "--output-format", "json",
         "--tools", "", "--permission-mode", "dontAsk", "--no-session-persistence", prompt],
        env=env, capture_output=True, text=True, timeout=180,
    )
    try:
        data = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError((result.stderr or "Claude Code failed")[-500:])
    if data.get("is_error"):
        raise RuntimeError(str(data.get("result") or "Claude Code returned an error"))
    if result.returncode:
        raise RuntimeError((result.stderr or "Claude Code failed")[-500:])
    return str(data.get("result") or "")


TOOL = {
    "name": "ask_claude_subscription",
    "description": (
        "Ask Claude Code, authenticated through the user's Claude subscription, for "
        "a bounded read-only second opinion, draft, or analysis. Include all needed "
        "context in the prompt. No files or tools are available to Claude. Use "
        "selectively; Codex owns the task, edits, and final verification."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"prompt": {"type": "string", "description": "Self-contained prompt, at most 12000 characters."}},
        "required": ["prompt"],
        "additionalProperties": False,
    },
}


def handle(message):
    method = message.get("method")
    if method == "initialize":
        return {
            "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
            "serverInfo": {"name": "claude-subscription", "version": "1.0.0"},
            "instructions": (
                "Use ask_claude_subscription only for bounded independent read-only work "
                "where another model's perspective helps. Keep orchestration, file edits, "
                "and final verification with Codex. If Claude subscription login is unavailable, "
                "continue without it. Never pass secrets or unnecessary private context."
            ),
        }
    if method == "tools/list":
        return {"tools": [TOOL]}
    if method == "ping":
        return {}
    if method == "tools/call":
        params = message.get("params") or {}
        prompt = (params.get("arguments") or {}).get("prompt")
        if params.get("name") != TOOL["name"] or not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
            return {"content": [{"type": "text", "text": "Invalid tool or prompt (1–12000 characters required)."}], "isError": True}
        try:
            return {"content": [{"type": "text", "text": ask(prompt)}]}
        except Exception as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    raise ValueError("Method not found")


def main():
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if "id" not in message:
                continue
            try:
                output = {"jsonrpc": "2.0", "id": message["id"], "result": handle(message)}
            except Exception as exc:
                output = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": str(exc)}}
            print(json.dumps(output), flush=True)
        except Exception as exc:
            print(f"Claude MCP error: {exc}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
