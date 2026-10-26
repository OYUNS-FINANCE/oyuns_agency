# 0010 — LLM provider configuration from the UI
Date: 2026-10-26    Status: accepted

## Context
Provider, API keys and per-agent models were environment variables, so changing them meant
editing backend env files and restarting. Users need to configure providers from the UI.

## Options considered
1. Write the UI values back to `.env` — breaks in containers (read-only, per-process), needs restarts.
2. Store plaintext in the database — simple, but a database dump leaks keys.
3. Store in the database with keys encrypted (Fernet) and layer it over the environment — chosen.

## Decision
- Table `llm_settings` (one row per user): provider, base URL, per-provider encrypted keys, and the
  seven agent models. A row fully specifies provider and models; keys fall back to the environment.
- `SETTINGS_ENCRYPTION_KEY` (Fernet) is the only new secret in the environment. Required in
  production (compose refuses to start without it); local/test use a fixed development key so the
  API and worker agree without setup.
- `run_deps` (now async) resolves effective settings per run via `effective_settings`, so a change
  applies to the next run with no restart and an in-flight run is unaffected.
- The API never returns a key: only `is_set`, the last four characters and where it comes from.
  `PUT` keeps the stored key when none is sent. `POST /test` makes one tiny real call without saving.
- OpenAI-compatible gateways are supported through a base URL on the OpenAI provider.

## Consequences
- No env change needed for existing setups: without a row the environment decides, as before.
- Anyone who can reach the UI can change the key — single-user mode, no auth yet (known issue).
- Losing `SETTINGS_ENCRYPTION_KEY` makes saved keys unreadable (treated as unset; re-enter them).
- Models absent from `pricing.PRICES` cost 0 in the budget/daily cap (a warning is logged).
- Search provider keys are still environment-only.
