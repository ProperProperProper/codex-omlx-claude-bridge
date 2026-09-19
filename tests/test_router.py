import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from routing_core import Router


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = Path(self.tmp.name) / "state.sqlite3"
        self.time = 1_000_000.0
        self.calls = []
        self.router = Router(self.database, self.claude, self.omlx, lambda: self.time)

    def claude(self, prompt):
        self.calls.append("claude")
        return "Claude answer"

    def omlx(self, prompt):
        self.calls.append("omlx")
        return "Local answer"

    def test_python_route_and_privacy(self):
        self.assertEqual(self.router.delegate("Write a Python docstring", kind="docs")["source"], "omlx")
        self.assertEqual(self.router.delegate("Analyze an asyncio race condition")["source"], "claude")
        self.assertEqual(self.router.delegate("Analyze an asyncio race condition", privacy="local_only")["source"], "omlx")
        self.assertEqual(self.router.delegate("Investigate api_key=sk-abcdef1234567890XYZ", mode="deep")["source"], "omlx")
        self.assertEqual(self.calls, ["omlx", "claude", "omlx", "omlx"])

    def test_quota_circuit_shared_and_recovery(self):
        def limited(_):
            self.calls.append("claude")
            raise RuntimeError("You've hit your weekly limit · resets 7am")
        self.router.claude = limited
        first = self.router.delegate("Analyze Python concurrency architecture")
        self.assertEqual(first["source"], "omlx")
        self.assertEqual(first["fallback"], ["claude: subscription_limit"])
        self.assertGreaterEqual(self.router.status()["providers"]["claude"]["cooldown_seconds"], 3500)
        another = Router(self.database, self.claude, self.omlx, lambda: self.time)
        self.assertEqual(another.delegate("Analyze Python concurrency architecture")["source"], "omlx")
        self.assertEqual(self.calls.count("claude"), 1)
        self.time += 3601
        self.assertEqual(another.delegate("Analyze Python concurrency architecture")["source"], "claude")

    def test_local_failure_does_not_spend_claude_quota(self):
        def unavailable(_):
            self.calls.append("omlx")
            raise OSError("connection refused")
        self.router.omlx = unavailable
        result = self.router.delegate("Write a small Python function", kind="snippet")
        self.assertEqual(result["source"], "codex")
        self.assertEqual(self.calls, ["omlx"])
        self.assertEqual(self.router.delegate("Write another function", kind="snippet")["source"], "codex")
        self.assertEqual(self.calls, ["omlx"])

    def test_no_prompt_or_response_persisted(self):
        secret_context = "context-should-never-be-stored"
        self.router.delegate("Write tests for " + secret_context, kind="tests")
        db = sqlite3.connect(self.database)
        try:
            values = db.execute("SELECT name, last_error FROM providers").fetchall()
        finally:
            db.close()
        self.assertNotIn(secret_context, json.dumps(values))


if __name__ == "__main__":
    unittest.main()
