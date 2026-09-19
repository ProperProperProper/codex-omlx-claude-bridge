# Model routing preference

Use oMLX as the free, local-first control plane for bounded Python reasoning. Use the Codex app for workspace tools, edits, integration, tests, and final verification.

For useful bounded Python subtasks, prefer `smart_models.delegate_readonly` with `mode="auto"`. Auto always stays on oMLX, including architecture, concurrency, performance, and subtle bug analysis. Use `routing_plan` when the decision needs to be visible. Escalate only a clearly valuable, self-contained second opinion with `mode="deep"`; Claude limits automatically fall back to oMLX. Supply only the relevant excerpt and context. Respect `privacy="local_only"` when external delegation is inappropriate.

Do not delegate trivial tasks simply to use all providers. Claude receives only the supplied prompt and cannot inspect task files through this tool. Never send secrets or unnecessary private context. Check delegated claims and code yourself. If the router is unavailable, continue in Codex. Never switch Claude to API-key billing automatically.

If a Codex or Claude session ends, use `continuity.py` with the self-contained next subtask. The desktop apps do not expose a callback that can start a bridge request after a session limit has stopped the app, so it cannot resume a task invisibly. The continuity command shares routing state, stays oMLX-first, returns JSON, and does not edit files.
