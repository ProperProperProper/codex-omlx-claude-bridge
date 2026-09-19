#!/usr/bin/env python3
"""Run the same local-first router outside a live Codex task.

This is intentionally read-only. An external launcher, shell script, or user can
invoke it after a Codex task ends; it cannot observe Codex subscription state.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from claude_subscription_mcp import ask as ask_claude
from omlx_mcp import local_response as ask_omlx
from routing_core import Router


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded task through the local-first bridge.")
    parser.add_argument("prompt", nargs="?", help="Task text; stdin is used when omitted.")
    parser.add_argument("--mode", choices=("auto", "fast", "deep", "local_only"), default="auto")
    parser.add_argument("--kind", default="auto")
    parser.add_argument("--privacy", choices=("standard", "local_only"), default="standard")
    parser.add_argument("--plan", action="store_true", help="Print routing plan without inference.")
    args = parser.parse_args()
    prompt = args.prompt if args.prompt is not None else sys.stdin.read()
    database = Path(os.environ.get(
        "SMART_MODELS_DB", str(Path.home() / "Documents" / "Codex" / ".integrations" / "smart-model-router" / "state.sqlite3")
    )).expanduser()
    router = Router(database, ask_claude, ask_omlx)
    try:
        result = router.plan(prompt, args.mode, args.kind, args.privacy) if args.plan else router.delegate(
            prompt, args.mode, args.kind, args.privacy
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("source", "ok") != "codex" else 2


if __name__ == "__main__":
    raise SystemExit(main())
