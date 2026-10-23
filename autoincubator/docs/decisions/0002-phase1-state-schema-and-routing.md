# 0002 — Phase-1 graph: state schema, routing and checkpoint semantics
Date: 2026-10-23    Status: accepted

## Context
Phase 1 runs Scout → Analyst → Skeptic as a LangGraph `StateGraph` (langgraph 1.2.16,
langgraph-checkpoint 4.3.0, langgraph-checkpoint-postgres 3.2.0). The graph pauses at a
human checkpoint with `interrupt()` and must resume days later in a different process from
the Postgres checkpoint (`thread_id = run_id`). The spec requires one loop back to the
Scout when fewer than 3 ideas pass the quality threshold, honest reporting when the loop
does not help, and Phase-2 nodes behind the checkpoint.

## Options considered
1. **State as plain dicts** (`model_dump(mode="json")` everywhere): always serialisable,
   but every node re-validates and types are lost at node boundaries.
2. **Pydantic models in a `TypedDict` state with reducers** (chosen): typed end to end;
   needs the checkpointer's msgpack serde to rebuild the models.
3. **Fan-out per idea with `Send`** vs **bounded `asyncio.gather` inside each node**:
   `Send` gives per-idea tasks and checkpoints but more graph plumbing; gather is simpler
   and per-idea events can still be emitted from inside the node in Phase 2.
4. **Routing decision in a conditional-edge function reading settings** vs **in the rank
   node**: edge functions get only state, so settings would have to be closed over at build
   time, a second source of truth next to the runtime context.

## Decision
- **State (`app/graph/state.py`, `Phase1State`, `total=False`):** `run_id`, `run_input`,
  `iteration` (Scout passes done), `opportunities` (reducer `merge_by_id`), `analyses` and
  `critiques` (dicts keyed by opportunity id, reducer `merge_dict`), `composite_scores`,
  `briefs`, `viable_count`, `loop_back`, `shortfall` (replaced on every rank pass),
  `usage` (`operator.add`; one `UsageRecord` per LLM attempt), `selected_idea_id`,
  `phase2` (`merge_dict`, stub markers).
- **Incremental work:** Analyst and Skeptic only process ids missing from `analyses` /
  `critiques`, so the loop back pays only for new candidates. Opportunity ids are
  `opp-NN`, continuing across passes; dedup (`JaccardDeduplicator`, behind the
  `Deduplicator` protocol) runs against all earlier opportunities.
- **Dependencies** (LLM, search, dedup, settings) are a `GraphDeps` dataclass passed as
  LangGraph *context* (`context_schema=GraphDeps`, `ainvoke(..., context=deps)`), never
  checkpointed; a resuming process supplies fresh providers.
- **Ranking is Python:** composite = weighted mean of the seven rubric scores (1-10,
  10 = favourable), weights from `RUBRIC_WEIGHT_*`, normalised. Viable = composite ≥
  `QUALITY_THRESHOLD`. `briefs` = top `MAX_BRIEFS` viable ideas, never padded.
- **Routing:** the rank node decides `loop_back = viable < MIN_VIABLE_IDEAS and
  iteration < MAX_SCOUT_ITERATIONS` (default 2 → exactly one loop back). `route_after_rank`
  only reads that flag. When the last pass still has too few, rank writes an honest
  `shortfall` message and the graph proceeds to the checkpoint.
- **Checkpoint:** `checkpoint` calls `interrupt(CheckpointPayload)` (briefs, viable count,
  shortfall, iterations, error). Resume with `Command(resume={"selected_idea_id": ...})`.
  An invalid answer is answered with a *further* `interrupt()` carrying `error`, not with
  an exception: LangGraph replays earlier resume values to earlier `interrupt()` calls on
  every re-run, so raising would replay the bad value forever.
- **Phase 2:** `product_architect`, `gtm_strategist`, `financial_modeler` fan out from the
  checkpoint in parallel and join into `editor`; all four are no-op stubs until Phase 5.
- **Checkpointer:** `AsyncPostgresSaver.from_conn_string(...)` + `setup()`, in the app
  database. Its tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`,
  `checkpoint_migrations`) are owned by LangGraph and excluded from Alembic autogenerate.
  `InMemorySaver` is used only in unit tests.
- **Serialisation:** LangGraph 1.2 derives the msgpack allowlist from the state schema's
  type hints at `compile()`, so every model reachable from `Phase1State` round-trips.
  URLs are stored as `WebUrl` (validated like `HttpUrl`, stored as `str`), because
  pydantic `Url` objects are not msgpack-serialisable.

## Consequences
- Adding a state field means adding it to `Phase1State` with a type, or it will not
  deserialise under `LANGGRAPH_STRICT_MSGPACK` (the integration test runs in strict mode).
- Everything before `interrupt()` in `checkpoint` re-runs on each resume and must stay
  side-effect free; Phase 4 (cowork) must not move DB writes into that node.
- `briefs` is a snapshot at interrupt time. SPEC §6 (resume reloads the latest idea
  versions from the DB) is not implemented yet; revisit in Phase 3/4 with the app tables.
- Per-idea failures (no valid output after retries) leave that idea unanalysed/unscored
  instead of failing the run; it can be retried on a loop-back pass.
