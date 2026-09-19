#!/usr/bin/env python3
"""Small stdio MCP bridge from Codex to a local oMLX Responses endpoint."""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

MODEL = os.environ.get("OMLX_MODEL", "mlx-community/Qwen2.5-Coder-7B-Instruct-8bit")
OMLX_BIN = os.environ.get("OMLX_BIN", "omlx")
SETTINGS = Path.home() / ".omlx" / "settings.json"


def config():
    data = json.loads(SETTINGS.read_text())
    server = data.get("server", {})
    port = int(server.get("port", 8000))
    key = data.get("auth", {}).get("api_key") or "omlx"
    return f"http://127.0.0.1:{port}/v1", key


def local_response(prompt):
    base, key = config()
    body = json.dumps({"model": MODEL, "input": prompt, "max_output_tokens": 1000}).encode()
    req = urllib.request.Request(
        base + "/responses", body,
        {"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.load(response)
    except urllib.error.URLError as exc:
        if not isinstance(exc.reason, ConnectionRefusedError):
            raise
        # Recover a stopped managed server once. Never retry a model request
        # after it reached the service, which could duplicate paid work.
        started = subprocess.run(
            [OMLX_BIN, "start", "--timeout", "20"],
            capture_output=True, text=True, timeout=25,
        )
        if started.returncode:
            raise RuntimeError("oMLX server could not start") from exc
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.load(response)
    if isinstance(result.get("output_text"), str):
        return result["output_text"]
    parts = []
    for item in result.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                parts.append(content.get("text", ""))
    return "\n".join(parts) or json.dumps(result)


TOOL = {
    "name": "ask_local_model",
    "description": (
        "Ask the Mac's oMLX model for a bounded, read-only subtask. Useful for "
        "drafts, summaries, brainstorming, classification, and an independent "
        "second opinion on short code excerpts. The local model cannot see "
        "the conversation or files unless you include their relevant text. "
        "Keep final decisions, edits, and verification with Codex."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"prompt": {"type": "string", "description": "Self-contained task and context, at most 12000 characters."}},
        "required": ["prompt"],
        "additionalProperties": False,
    },
}


def handle(msg):
    method = msg.get("method")
    if method == "initialize":
        return {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "omlx-local", "version": "1.0.0"},
            "instructions": (
                "Use ask_local_model selectively for short, self-contained, read-only subtasks "
                "when the local oMLX model can save work: drafting, summarizing, classification, "
                "brainstorming, or a second opinion on a small code excerpt. Keep task planning, "
                "tool use, file edits, high-stakes judgments, and final verification with Codex. "
                "If oMLX is unavailable, continue with Codex. Do not send secrets or unnecessary "
                "private context."
            ),
        }
    if method == "tools/list":
        return {"tools": [TOOL]}
    if method == "tools/call":
        params = msg.get("params") or {}
        if params.get("name") != TOOL["name"]:
            return {"content": [{"type": "text", "text": "Unknown tool"}], "isError": True}
        prompt = (params.get("arguments") or {}).get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
            return {"content": [{"type": "text", "text": "Prompt must contain 1–12000 characters."}], "isError": True}
        try:
            answer = local_response(prompt)
            return {"content": [{"type": "text", "text": answer}]}
        except (OSError, urllib.error.URLError, ValueError, KeyError) as exc:
            return {"content": [{"type": "text", "text": f"oMLX unavailable: {exc}"}], "isError": True}
    if method == "ping":
        return {}
    raise ValueError("Method not found")


def main():
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if "id" not in message:
                continue
            try:
                result = {"jsonrpc": "2.0", "id": message["id"], "result": handle(message)}
            except Exception as exc:
                result = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": str(exc)}}
            print(json.dumps(result), flush=True)
        except Exception as exc:
            print(f"oMLX MCP error: {exc}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
