import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import claude_subscription_mcp as claude
import omlx_mcp as omlx


class ClaudeBillingGuardTests(unittest.TestCase):
    def test_rejects_api_key_without_invoking_model(self):
        status = json.dumps({"loggedIn": True, "authMethod": "api_key", "apiKeySource": "ANTHROPIC_API_KEY"})
        with patch.object(claude.subprocess, "run", return_value=type("Process", (), {"stdout": status, "stderr": "", "returncode": 0})()) as run:
            with self.assertRaisesRegex(RuntimeError, "subscription login is not active"):
                claude.ask("test")
            self.assertEqual(run.call_count, 1)

    def test_subscription_invocation_scrubs_api_key(self):
        status = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiKeySource": None})
        answer = json.dumps({"is_error": False, "result": "ok"})
        outcomes = [type("Process", (), {"stdout": text, "stderr": "", "returncode": 0})() for text in (status, answer)]
        with patch.dict(claude.os.environ, {"ANTHROPIC_API_KEY": "sentinel", "ANTHROPIC_BASE_URL": "sentinel"}):
            with patch.object(claude.subprocess, "run", side_effect=outcomes) as run:
                self.assertEqual(claude.ask("test"), "ok")
                for call in run.call_args_list:
                    self.assertNotIn("ANTHROPIC_API_KEY", call.kwargs["env"])
                    self.assertNotIn("ANTHROPIC_BASE_URL", call.kwargs["env"])


class LocalRecoveryTests(unittest.TestCase):
    def test_restart_once_on_refused_connection(self):
        payload = json.dumps({"output_text": "local ok"}).encode()
        response = io.BytesIO(payload)
        failure = urllib.error.URLError(ConnectionRefusedError())
        with patch.object(omlx, "config", return_value=("http://127.0.0.1:8000/v1", "secret")):
            with patch.object(omlx.urllib.request, "urlopen", side_effect=[failure, response]) as open_url:
                with patch.object(omlx.subprocess, "run", return_value=type("Process", (), {"returncode": 0})()) as start:
                    self.assertEqual(omlx.local_response("test"), "local ok")
                    self.assertEqual(start.call_count, 1)
                    self.assertEqual(open_url.call_count, 2)


if __name__ == "__main__":
    unittest.main()
