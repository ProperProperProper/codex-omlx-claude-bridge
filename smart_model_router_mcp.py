#!/usr/bin/env python3
"""MCP adapter for bounded Python model delegation."""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from claude_subscription_mcp import CLAUDE, SETTINGS, ask as ask_claude, clean_env
from omlx_mcp import MODEL, config as omlx_config, local_response as ask_omlx
from routing_core import Router

DATABASE = Path(os.environ.get(
    "SMART_MODELS_DB",
    str(Path.home() / "Documents" / "Codex" / ".integrations" / "smart-model-router" / "state.sqlite3"),
)).expanduser()
_router = None


def router():
    global _router
    if _router is None:
        _router = Router(DATABASE, ask_claude, ask_omlx)
    return _router


def live_health():
    health = {"claude_subscription_auth": False, "omlx_server": False, "omlx_model_installed": (Path.home() / ".omlx" / "models" / MODEL).is_dir()}
    try:
        result = subprocess.run(
            [CLAUDE, "--settings", SETTINGS, "auth", "status", "--json"],
            env=clean_env(), capture_output=True, text=True, timeout=15,
        )
        auth = json.loads(result.stdout)
        health["claude_subscription_auth"] = bool(auth.get("loggedIn") and auth.get("authMethod") == "claude.ai" and not auth.get("apiKeySource"))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    try:
        base, key = omlx_config()
        req = urllib.request.Request(base + "/models", headers={"Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=3) as response:
            models = json.load(response).get("data", [])
        health["omlx_server"] = True
        health["omlx_exposed_ids"] = [item.get("id") for item in models[:10]]
    except (OSError, ValueError):
        pass
    return health


TOOLS = [
    {
        "name": "delegate_readonly",
        "description": (
            "Route one bounded read-only Python coding subtask. Auto is oMLX-first; "
            "mode=deep explicitly escalates to Claude Pro, with oMLX fallback. No "
            "file access or edits."
        ),
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Self-contained task and context, at most 12000 characters."},
                "mode": {"type": "string", "enum": ["auto", "fast", "deep", "local_only"], "description": "Optional routing preference; default auto."},
                "kind": {"type": "string", "enum": ["auto", "snippet", "docs", "tests", "explain", "architecture", "deep_review", "complex_debug", "performance", "security"], "description": "Optional Python task category; default auto."},
                "privacy": {"type": "string", "enum": ["standard", "local_only"], "description": "Keep the prompt on the Mac when local_only; default standard."},
            },
            "required": ["prompt"], "additionalProperties": False,
        },
    },
    {
        "name": "routing_plan",
        "description": "Preview the local-first routing decision, cooldown, and active capacity without invoking a model.",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Self-contained task and context, at most 12000 characters."},
                "mode": {"type": "string", "enum": ["auto", "fast", "deep", "local_only"]},
                "kind": {"type": "string", "enum": ["auto", "snippet", "docs", "tests", "explain", "architecture", "deep_review", "complex_debug", "performance", "security"]},
                "privacy": {"type": "string", "enum": ["standard", "local_only"]},
            },
            "required": ["prompt"], "additionalProperties": False,
        },
    },
    {
        "name": "routing_status",
        "description": "Show provider cooldowns, success counts, and latency. Set probe=true to check live authentication and oMLX model availability without model inference.",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {"probe": {"type": "boolean", "description": "Run live, non-inference health checks; default false."}}, "additionalProperties": False},
    },
]


def handle(message):
    method = message.get("method")
    if method == "initialize":
        return {
            "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
            "serverInfo": {"name": "smart-model-router", "version": "1.0.0"},
            "instructions": (
                "Codex is the OpenAI coordinator for Python coding. Use delegate_readonly "
                "selectively for bounded independent analysis. Auto mode is local-first: oMLX "
                "is the control plane and Claude Pro is used only for mode=deep escalation. "
                "Subscription limits and outages fall back automatically. Do not delegate edits, execution, "
                "secrets, or high-stakes decisions. Verify all returned work in Codex."
            ),
        }
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "ping":
        return {}
    if method == "tools/call":
        params = message.get("params") or {}
        if params.get("name") == "routing_status":
            result = router().status()
            if (params.get("arguments") or {}).get("probe") is True:
                result["live_health"] = live_health()
        elif params.get("name") == "delegate_readonly":
            args = params.get("arguments") or {}
            result = router().delegate(args.get("prompt"), args.get("mode", "auto"), args.get("kind", "auto"), args.get("privacy", "standard"))
        elif params.get("name") == "routing_plan":
            args = params.get("arguments") or {}
            result = router().plan(args.get("prompt"), args.get("mode", "auto"), args.get("kind", "auto"), args.get("privacy", "standard"))
        else:
            raise ValueError("Unknown tool")
        return {"content": [{"type": "text", "text": json.dumps(result)}], "isError": result.get("source") == "codex"}
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
                output = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32602, "message": str(exc)}}
            print(json.dumps(output), flush=True)
        except Exception as exc:
            print(f"Router MCP error: {exc}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
