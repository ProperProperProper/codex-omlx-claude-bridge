import json
import sqlite3
import sys
import tempfile
import threading
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
        self.assertEqual(self.router.delegate("Analyze an asyncio race condition")["source"], "omlx")
        self.assertEqual(self.router.delegate("Analyze an asyncio race condition", mode="deep")["source"], "claude")
        self.assertEqual(self.router.delegate("Analyze an asyncio race condition", privacy="local_only")["source"], "omlx")
        self.assertEqual(self.router.delegate("Investigate api_key=sk-abcdef1234567890XYZ", mode="deep")["source"], "omlx")
        self.assertEqual(self.calls, ["omlx", "omlx", "claude", "omlx", "omlx"])

    def test_plan_is_local_first_and_exposes_capacity(self):
        plan = self.router.plan("Review a Python asyncio race condition", kind="complex_debug")
        self.assertEqual(plan["preferred"], "omlx")
        self.assertEqual(plan["candidates"], ["omlx"])
        self.assertEqual(plan["availability"]["omlx"]["capacity"], 2)
        self.assertEqual(self.router.plan("Review a Python race", mode="deep")["preferred"], "claude")

    def test_capacity_lease_prevents_duplicate_claude_work(self):
        one, reason = self.router._reserve("claude")
        self.assertIsNotNone(one)
        two, reason = self.router._reserve("claude")
        self.assertIsNone(two)
        self.assertEqual(reason, "busy")
        self.router._release(one)

    def test_local_capacity_and_expired_lease_recovery(self):
        first, _ = self.router._reserve("omlx")
        second, _ = self.router._reserve("omlx")
        third, reason = self.router._reserve("omlx")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNone(third)
        self.assertEqual(reason, "busy")
        self.time += 206
        recovered, reason = self.router._reserve("omlx")
        self.assertIsNotNone(recovered)
        self.assertIsNone(reason)

    def test_concurrent_router_startup_shares_database(self):
        errors = []

        def start_router():
            try:
                Router(self.database, self.claude, self.omlx, lambda: self.time)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=start_router) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])

    def test_quota_circuit_shared_and_recovery(self):
        def limited(_):
            self.calls.append("claude")
            raise RuntimeError("You've hit your weekly limit · resets 7am")
        self.router.claude = limited
        first = self.router.delegate("Analyze Python concurrency architecture", mode="deep")
        self.assertEqual(first["source"], "omlx")
        self.assertEqual(first["fallback"], ["claude: subscription_limit"])
        self.assertGreaterEqual(self.router.status()["providers"]["claude"]["cooldown_seconds"], 3500)
        another = Router(self.database, self.claude, self.omlx, lambda: self.time)
        self.assertEqual(another.delegate("Analyze Python concurrency architecture", mode="deep")["source"], "omlx")
        self.assertEqual(self.calls.count("claude"), 1)
        self.time += 3601
        self.assertEqual(another.delegate("Analyze Python concurrency architecture", mode="deep")["source"], "claude")

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
