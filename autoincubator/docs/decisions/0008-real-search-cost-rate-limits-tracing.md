# 0008 — Real search, cost control, rate limits and tracing
Date: 2026-10-24    Status: accepted

## Context
Phase 6 moves from fakes to real providers. Real runs cost money and fetch content we don't
control. A run also spans several processes (the API, two worker jobs separated by a human
pause that can last days, and co-working chat). We will deploy on one VPS with Dokploy:
Traefik in front, Postgres and Redis next to the app, and no managed observability stack.

## Options considered
**Tracing**
1. LangSmith: LangGraph-aware views out of the box. But it is a hosted SaaS with its own key,
   it only sees what LangChain instruments (not our HTTP layer, the arq jobs or the search
   calls), and it ties the stack to one vendor.
2. OpenTelemetry (OTLP): vendor-neutral, and it covers everything: HTTP, jobs, nodes, LLM and
   search calls. Any backend works (Jaeger locally, Grafana Tempo or a hosted OTLP endpoint in
   production). It costs nothing when off. The cost is that we instrument by hand.

**Linking a run's processes into one trace**
1. Propagate W3C trace context through the arq job payload. It breaks across the checkpoint
   pause (the resume job is enqueued by a different request) and across worker recovery.
2. Derive the trace id from the run's UUID. Every process that works on a run opens a root
   span in that trace, with nothing to propagate. Lookup is trivial: paste the run id into
   the tracing UI.

**Search providers**: Tavily (an LLM-oriented API with clean snippets) or Serper (Google
results, cheaper per query). Both sit behind the existing `SearchProvider` protocol.

**Rate limiting**: slowapi, or a small fixed-window counter in the Redis we already run.

## Decision
- **OpenTelemetry**, exported over OTLP/HTTP only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
  **A run's trace id is its UUID** (`RunIdGenerator` + `run_span`).
  - Root spans in a run's trace:
    - every API request whose path carries the run id;
    - the enqueue in `POST /runs`, which records the creating request's trace id, because
      that request has no run id in its path;
    - each worker job.
  - Nodes, LLM attempts and searches nest under the worker job.
  - structlog binds `run_id`, `node`, `request_id` and the trace/span ids into every log line.
  - Locally: `docker compose --profile tracing up -d jaeger`.
- **Search**: Tavily is the default for real runs; Serper is the alternative
  (`SEARCH_PROVIDER`). The chain is built in `providers/search/factory.py`:
  - **Per-run cache + budget hooks.** Cache hits are free.
  - **Sanitiser.** It strips markup and invisible or format characters, then redacts
    sentences that read as instructions to a model and logs each redaction. It **drops a
    result that is only instructions**, because that result carries no data, only a URL a
    model could cite. Finally it caps lengths. It runs before the existing
    `<untrusted_web_content>` wrapping and the prompt rules.
  - **Cross-run Postgres cache** (`search_result_cache`, TTL `SEARCH_CACHE_TTL_S`). The
    sanitiser sits outside it, so tightening a rule also cleans old entries.
  - **HTTP provider.**
    - Retries timeouts, connection errors and 408/425/429/5xx with jittered exponential
      backoff, honouring `Retry-After`. Other errors fail at once.
    - A token bucket per process (`SEARCH_RATE_PER_S`).
    - One pooled client per provider.
- **Models**: the defaults route per agent:
  - Haiku for the Scout (high volume, extraction);
  - Sonnet for the Analyst and the Phase-2 builders;
  - Opus for the Skeptic and Editor (judgement).
  - Every agent can be overridden with `*_MODEL`. Anthropic prompt caching marks the static
    system prompts, and the first user turn on a validation retry.
- **Cost**:
  - `run_costs` gets one row per LLM attempt, priced from `pricing.py`.
  - The run detail returns cost per agent and model, and the run page shows it.
  - **Global daily cap** `DAILY_COST_CAP_USD` (UTC day, all runs):
    - checked when a run is created (429 `daily_cap_reached`);
    - checked before every LLM attempt, which stops the run as `budget_exhausted` with
      kind `daily_cost`.
- **Rate limits**:
  - Fixed windows in Redis, per client: run creation per hour, LLM-starting endpoints per
    minute, everything else per minute. SSE and health checks are exempt.
  - The client is the socket peer, or the address `TRUSTED_PROXY_HOPS` entries from the
    right of `X-Forwarded-For` (set to 1 behind Dokploy's Traefik).
  - A Redis outage fails open.

## Consequences
- One trace per run makes a whole run debuggable from its id. The roots are siblings, not a
  tree: a resume is not a child of the first job.
- The `POST /runs` HTTP span itself is in its own trace, reachable via
  `http.request_trace_id`.
- A deterministic trace id means a run id must never be reused. UUIDv4 makes that a
  non-issue.
- Spend is bounded twice: per run (tokens, searches) and per day (USD). The daily check is a
  `SUM` over an indexed `created_at` per LLM call. Parallel calls can overshoot a cap by at
  most one call each.
- Injection hygiene is heuristic and can miss novel phrasings. It is defence in depth on top
  of the delimiters and prompt rules, not a guarantee. Redactions are logged
  (`search.injection_suspected` / `search.injection_dropped`) so they can be audited.
- Fixed windows allow a burst of up to twice the limit at a window edge. That is acceptable
  for a single-user deployment; revisit when auth and per-user quotas arrive.
- The evals (`backend/tests/evals/`) are manual and cost real money. `collect` has its own
  `--max-cost` guard, because it runs in-process and bypasses the DB-backed daily cap.
