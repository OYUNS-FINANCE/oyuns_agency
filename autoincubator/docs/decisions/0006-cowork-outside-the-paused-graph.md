# 0006 — Co-working while the graph is paused: external service, DB versions, resume with the chosen brief
Date: 2026-10-23    Status: accepted

## Context
At the checkpoint the graph is suspended in `interrupt()` (ADR 0002). For days at a time, the
founder chats with Scout/Analyst/Skeptic about one idea, accepts edits as new versions,
re-scores, rejects and merges ideas, then selects one. Selecting resumes the graph into
Phase 2. SPEC §6 sketches an approach and asks for it to be confirmed with an ADR.

Constraints:
- The checkpoint node re-runs from the top on every resume, and LangGraph replays earlier
  resume values to earlier `interrupt()` calls. Everything before the final `interrupt()`
  must stay side-effect free (ADR 0002).
- Only one job may drive a run's graph at a time (job leases, ADR 0004).
- The UI needs full version history with diffs, per-idea chat logs, and state that survives
  a page reload. These are application data, not execution state.
- SPEC §6: application tables are the source of truth for ideas; checkpoints hold execution
  state only.

## Options considered
1. **External `services/cowork` + DB versions; resume carries the selection (chosen).**
   Chat, re-score and merge are agent calls made outside the graph. Accepted changes write
   `idea_versions` rows. Select resumes the graph once.
   - Pros: the graph stays untouched while paused, so no lease juggling and no checkpoint
     growth. Versions, diffs and chat history are ordinary queryable rows. Each action is
     independently testable. A failed chat call cannot corrupt the checkpoint.
   - Cons: two copies of the briefs exist (the checkpoint snapshot and the DB). Resume must
     bring the DB's version into the graph.
2. **`aupdate_state` on the checkpoint for every accepted change.**
   - Pros: the graph state is always current.
   - Cons: every edit forks a checkpoint while the run is interrupted. `as_node` semantics
     around a pending interrupt are subtle. Concurrent edits race on the checkpoint, so they
     need the run lease, which ADR 0004 reserves for graph execution. History lives in
     checkpoint blobs, which aren't queryable for diffs. It also contradicts "checkpoints
     hold execution state only".
3. **A co-working subgraph: every action is a resume (`Command(resume={"action": ...})`)
   that runs a cowork node and interrupts again.**
   - Pros: all agent work goes through the graph, the worker and the lease.
   - Cons: every chat message becomes a worker job plus a checkpoint write, which adds
     latency to a conversation. The checkpoint node's replay list grows with every action,
     so the replay rule from ADR 0002 applies hundreds of times. A bad action can wedge the
     run. Token streaming of chat replies through the run event log is awkward.

## Decision
Option 1, with one revision to SPEC §6: the graph does not read the DB on resume. The
worker loads the selected idea's latest version and passes the whole brief in the resume
value. The graph stays deterministic, needs no DB dependency, and replays the same value
forever.

**Where each action runs**
| Action | Runs in | Why |
|---|---|---|
| Chat (`POST …/ideas/{id}/cowork`) | API, streamed response | One conversational LLM call; latency matters. Not a graph, so SPEC §6 ("the API never runs a graph") holds. |
| Apply patch (`POST …/ideas/{id}/versions`) | API | Pure Python: apply the JSON Patch, validate, insert a version. |
| Re-score (`…/rescore`) | Worker job | Agent work, reported on the run stream as `agent.*` + `idea.updated`. |
| Reject (`…/reject`) | API | DB write only. |
| Merge (`…/ideas/merge`) | Worker job | Synthesis + Analyst + Skeptic (with searches), streamed as `agent.*` + `idea.created`. |
| Select (`…/select`) | API transition + worker resume | See below. |

**Guards.** Every mutating co-working call takes `SELECT … FOR UPDATE` on the run and
returns `409 run_not_paused` unless the status is `awaiting_human`. Worker co-working jobs
re-check it before their final write, so they drop their output if the run was selected in
the meantime. Co-working jobs don't take the run lease: they never touch the checkpoint.

**Versions.** `idea_versions` rows are immutable. Each has `source` set to `cowork` (an
applied patch), `rescore` or `merge`. A `cowork` version keeps the previous critique and is
reported as `score_stale` until it is re-scored. Composite scores and ranks are recomputed
in Python (`composite_score`) across the run's active ideas after each re-score or merge.

**Patches** are RFC 6902 `add`/`replace`/`remove` operations on the brief's `opportunity` and
`analysis` only. The critique changes only through re-score. The patched brief must
re-validate: `SourcedFigure` still requires `source_url` or `assumption`, and any
`source_url` must already be cited by that idea. Chat has no search tool in Phase 4, so it
can't introduce new sources. The patch is validated inside the LLM retry loop, so a patch
that doesn't apply is fed back to the model.

**Select / resume.**
1. In one transaction, the API sets `runs.selected_idea_id`, sets the idea to `selected`, moves
   `awaiting_human → running`, and emits `run.resumed`. Then it enqueues `start_run` with job
   id `resume:{run_id}`.
2. The transition is conditional, so concurrent or repeated calls cannot double-resume. A
   repeat with the same idea returns `202` (idempotent). A different idea returns `409`.
3. The worker's `start_run` claims the lease as usual. It sees a pending interrupt plus a
   selection and calls `ainvoke(Command(resume={"idea_id": <uuid>, "brief": <latest
   version as IdeaBrief>}))`.
4. The checkpoint node validates the payload and writes `selected_idea_id` and
   `selected_brief` to state. Phase 2 reads `selected_brief`, so merged and edited ideas
   work without being in the interrupt snapshot.
5. Crash recovery is unchanged: a `running` run with a pending interrupt and a stored
   selection is re-resumed by the recovery sweep.

**Rejections** append `"<title>: <reason>"` to `founder_profile.rejected_idea_reasons`
(newest last, capped at `REJECTED_REASONS_MAX`). Mode B snapshots the profile into
`RunInput`, and `render_run_context` already shows those reasons to the Scout.

**Budget.** Co-working LLM and search calls are charged to the run's budget through the same
`RunBudget`. A co-working call that hits the cap fails with `409 budget_exhausted`, but the
run stays `awaiting_human` (ADR 0004 has no `awaiting_human → budget_exhausted` edge), so the
founder can still select. Phase 2 will then stop on its first call.

## Consequences
- `CheckpointPayload.briefs` becomes a historical snapshot. The DB is authoritative for what
  the founder sees and selects.
- The resume payload shape changes (`selected_idea_id` → `idea_id` + `brief`).
  `scripts/run_phase1.py --resume-select` builds the brief from the checkpoint snapshot.
- Chat replies aren't on the run event stream. A reload mid-reply re-reads
  `cowork_messages`. The user message is stored immediately. The reply is generated in a
  task that isn't bound to the request, so it is stored even if the client disconnects.
- Phase 5 must read `selected_brief`, not look up `briefs` by id.
- Adds a migration (`cowork_messages`; `runs.selected_idea_id`; `ideas.merged_from`;
  `idea_versions.patch` and `message_id`).
