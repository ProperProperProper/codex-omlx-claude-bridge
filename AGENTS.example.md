# Model routing preference

Use the Codex app as the main workspace and OpenAI coordinator, especially for Python coding. Codex owns planning, tools, edits, integration, tests, and final verification.

For useful bounded Python subtasks, prefer `smart_models.delegate_readonly` with `mode="auto"`. It routes simple isolated functions, docstrings, type hints, and test ideas to oMLX; deep architecture, concurrency, performance, and subtle bug analysis to Claude Pro when subscription capacity is available; and Claude limits back to oMLX. Supply only the relevant excerpt and context. Respect `privacy="local_only"` when external delegation is inappropriate.

Do not delegate trivial tasks simply to use all providers. Claude receives only the supplied prompt and cannot inspect task files through this tool. Never send secrets or unnecessary private context. Check delegated claims and code yourself. If the router is unavailable, continue in Codex. Never switch Claude to API-key billing automatically.
