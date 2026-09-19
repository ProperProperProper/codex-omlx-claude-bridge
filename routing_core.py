"""Provider policy, health tracking, and fallback for the Codex model router."""

from __future__ import annotations

import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

MAX_PROMPT = 12_000
MAX_ANSWER = 24_000
SENSITIVE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:api[_-]?key|access[_-]?token|"
    r"client[_-]?secret|password)\s*[:=]\s*[^\s<>{}]{8,}|\bsk-[A-Za-z0-9_-]{16,}",
    re.I,
)
DEEP = re.compile(
    r"\b(?:architecture|tradeoffs?|security|root cause|race condition|deadlock|"
    r"concurrency|asyncio|multiprocessing|performance bottleneck|profiling|"
    r"memory leak|algorithmic complexity|subtle regression|migration strategy|"
    r"failure modes?|distributed systems?|compare approaches)\b", re.I,
)
SIMPLE = re.compile(
    r"\b(?:docstring|type hints?|typing|small function|unit test ideas?|"
    r"pytest cases?|rename|summari[sz]e|explain this snippet)\b", re.I,
)
DEEP_KINDS = {"architecture", "deep_review", "complex_debug", "performance", "security"}
KINDS = DEEP_KINDS | {"auto", "snippet", "docs", "tests", "explain"}
MODES = {"auto", "fast", "deep", "local_only"}


class Router:
    def __init__(
        self,
        database: Path,
        claude: Callable[[str], str],
        omlx: Callable[[str], str],
        now: Callable[[], float] = time.time,
    ):
        self.database = Path(database)
        self.claude = claude
        self.omlx = omlx
        self.now = now
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS providers (name TEXT PRIMARY KEY, blocked_until REAL NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0, calls INTEGER NOT NULL DEFAULT 0, successes INTEGER NOT NULL DEFAULT 0, ewma_ms REAL, last_error TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS call_history (id INTEGER PRIMARY KEY, time REAL NOT NULL, provider TEXT NOT NULL, duration_ms INTEGER NOT NULL, outcome TEXT NOT NULL)")
            for name in ("claude", "omlx"):
                db.execute("INSERT OR IGNORE INTO providers (name) VALUES (?)", (name,))

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def status(self):
        with self._db() as db:
            rows = db.execute("SELECT name, blocked_until, failures, calls, successes, ewma_ms, last_error FROM providers").fetchall()
            recent = db.execute("SELECT provider, outcome, count(*) FROM call_history WHERE time > ? GROUP BY provider, outcome", (self.now() - 86400,)).fetchall()
        return {
            "providers": {
                name: {
                    "cooldown_seconds": max(0, int(blocked - self.now())),
                    "consecutive_failures": failures,
                    "calls": calls,
                    "successes": successes,
                    "latency_ewma_ms": round(ewma) if ewma is not None else None,
                    "last_error_kind": error,
                }
                for name, blocked, failures, calls, successes, ewma, error in rows
            },
            "last_24h": {name: {outcome: count for provider, outcome, count in recent if provider == name} for name in ("claude", "omlx")},
            "policy": "Codex owns edits and verification; read-only Python work routes to oMLX or Claude Pro",
        }

    def classify(self, prompt: str, mode: str = "auto", kind: str = "auto", privacy: str = "standard"):
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
            raise ValueError("prompt must contain 1–12000 characters")
        if mode not in MODES or kind not in KINDS or privacy not in ("standard", "local_only"):
            raise ValueError("invalid mode, task kind, or privacy value")
        sensitive = bool(SENSITIVE.search(prompt))
        if sensitive or privacy == "local_only" or mode == "local_only":
            return ("omlx", "local-only privacy policy", True)
        if mode == "deep":
            return ("claude", "explicit deep analysis", False)
        if mode == "fast":
            return ("omlx", "explicit fast response", False)
        if kind in DEEP_KINDS or DEEP.search(prompt):
            return ("claude", "complex Python analysis", False)
        if kind in {"snippet", "docs", "tests", "explain"} or SIMPLE.search(prompt):
            return ("omlx", "bounded Python snippet or documentation", False)
        if len(prompt) > 4500:
            return ("claude", "large independent analysis", False)
        if len(prompt) > 1200:
            providers = self.status()["providers"]
            local_ms = providers["omlx"]["latency_ewma_ms"]
            claude_ms = providers["claude"]["latency_ewma_ms"]
            if (local_ms and claude_ms and local_ms > 25_000
                    and claude_ms < local_ms * 0.7
                    and not providers["claude"]["cooldown_seconds"]):
                return ("claude", "observed latency favors Claude for this medium task", False)
        return ("omlx", "routine bounded task", False)

    def _blocked(self, name):
        with self._db() as db:
            row = db.execute("SELECT blocked_until FROM providers WHERE name=?", (name,)).fetchone()
        return bool(row and row[0] > self.now())

    def _record(self, name, duration_ms, error=None):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT failures, ewma_ms FROM providers WHERE name=?", (name,)).fetchone()
            failures, previous = row
            if error is None:
                ewma = duration_ms if previous is None else 0.3 * duration_ms + 0.7 * previous
                db.execute("UPDATE providers SET calls=calls+1, successes=successes+1, failures=0, blocked_until=0, ewma_ms=?, last_error=NULL WHERE name=?", (ewma, name))
                outcome = "success"
            else:
                failures += 1
                lowered = error.lower()
                if name == "claude" and ("weekly limit" in lowered or "usage limit" in lowered or "429" in lowered):
                    kind, delay = "subscription_limit", min(21_600, 3600 * 2 ** min(failures - 1, 3))
                elif "login" in lowered or "authentication" in lowered or "401" in lowered:
                    kind, delay = "auth", 900
                else:
                    kind, delay = "unavailable", min(300, 30 * 2 ** min(failures - 1, 4))
                db.execute("UPDATE providers SET calls=calls+1, failures=?, blocked_until=?, last_error=? WHERE name=?", (failures, self.now() + delay, kind, name))
                outcome = kind
            db.execute("INSERT INTO call_history (time, provider, duration_ms, outcome) VALUES (?, ?, ?, ?)", (self.now(), name, round(duration_ms), outcome))
            if db.execute("SELECT count(*) FROM call_history").fetchone()[0] > 5000:
                db.execute("DELETE FROM call_history WHERE id IN (SELECT id FROM call_history ORDER BY id LIMIT 1000)")

    def delegate(self, prompt: str, mode: str = "auto", kind: str = "auto", privacy: str = "standard"):
        first, reason, local_only = self.classify(prompt, mode, kind, privacy)
        # Preserve Claude subscription capacity for genuinely deep work. Local-first
        # tasks return to Codex if oMLX fails instead of spending Claude quota.
        order = [first, "omlx"] if first == "claude" and not local_only else ["omlx"]
        failures = []
        for name in order:
            if self._blocked(name):
                failures.append(f"{name}: temporarily unavailable ({self.status()['providers'][name]['last_error_kind']})")
                continue
            started = time.monotonic()
            try:
                answer = self.claude(prompt) if name == "claude" else self.omlx(prompt)
                if not isinstance(answer, str) or not answer.strip():
                    raise RuntimeError("empty response")
                self._record(name, (time.monotonic() - started) * 1000)
                return {"source": name, "answer": answer[:MAX_ANSWER], "routing_reason": reason, "fallback": failures or None}
            except Exception as exc:
                # Only report a bounded error category; never store prompts or output.
                self._record(name, (time.monotonic() - started) * 1000, str(exc))
                failures.append(f"{name}: {self.status()['providers'][name]['last_error_kind']}")
        return {"source": "codex", "answer": "Handle this subtask in Codex; external models are unavailable.", "routing_reason": reason, "fallback": failures}
