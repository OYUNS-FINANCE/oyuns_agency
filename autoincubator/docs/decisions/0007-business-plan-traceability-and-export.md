# 0007 — Business plan: assembled in the graph, persisted at completion, numbers traced, PDF via WeasyPrint
Date: 2026-10-23    Status: accepted

## Context
Phase 5 turns the selected brief into a business plan. Agents 4–6 (Product Architect, GTM
Strategist, Financial Modeler) run in parallel, then the Editor reconciles them (SPEC §5).
The output is a Markdown and PDF dossier with a 30/60/90-day checklist and a "Sources &
Assumptions" appendix.

Constraints:
- **No invented numbers** (CLAUDE.md). Every number in the dossier must trace to a source,
  a stated assumption, or a calculation, and this must be checked automatically.
- **Financial math is Python, never LLM arithmetic.**
- The graph stays free of application-table access (ADR 0006). Checkpoints hold execution
  state; `business_plans` is the source of truth for the plan.
- The plan contains model-written text that derives from untrusted web content, and the
  server renders it into a PDF.
- The text may be in Cyrillic, including Mongolian (Ө, Ү).

## Options considered
**Where the plan is written**
1. **The Editor node returns `plan` in graph state; the worker persists it with
   `run.completed` (chosen).** This mirrors how the worker persists the checkpoint's briefs
   (ADR 0004). The graph never touches the DB, and the write happens in the same
   transaction as the terminal status, so a completed run always has its plan.
2. **The Editor node writes `business_plans` itself.** The node would need a DB dependency
   and must be idempotent across replays. That contradicts ADR 0006.

**Keeping numbers honest**
1. **A figure registry plus a number scanner (chosen).** Every number the plan may state is
   registered with its kind: a source URL, an assumption text, an estimate, an engine output
   with its formula, or a score. The scanner extracts each number from prose and from the
   rendered Markdown, and matches it by value at the precision it is written ("$1,234"
   matches 1234.4; "80%" matches 0.8). It runs:
   - (a) inside each agent's LLM retry loop, so an invented number is fed back to the model;
   - (b) on the brief, where Phase-1 text numbers that nothing supports become an
     `untraced_number` contradiction;
   - (c) on the final Markdown, as the acceptance check.
2. **Forbid digits in LLM prose entirely.** Simpler, but too strict: the summary should be
   able to quote "LTV $640", and the brief's own text legitimately contains numbers.
3. **Trust the prompts.** This doesn't satisfy "automated check".

**PDF**
1. **WeasyPrint, from the rendered Markdown (chosen).** Pure Python on top of Pango. It
   supports paged CSS (page breaks, repeated table headers, page counters) and is the phase
   file's default. Markdown is the single source, so the number check covers the PDF too.
2. **Headless Chromium (Playwright).** Renders HTML faithfully, but adds a browser and about
   300 MB to the backend image, plus a process per render.
3. **A separate HTML template next to the Markdown one.** That duplicates the content, and
   the two copies can drift apart, outside the number check.

## Decision
- **State and persistence.** The graph state gains `product`, `gtm`, `assumptions`,
  `financials` (computed by `services/finance.py`) and `plan` (`BusinessPlan`). `_complete`
  renders the Markdown and inserts `business_plans` v1 (unique per `(run_id, version)`,
  insert-or-nothing). It emits `run.completed {plan_version}` and moves the status, all in
  one transaction.
- **Sources.** Phase-2 agents don't search. A `source_url` may only be a URL the brief
  already cites; every other figure carries an assumption.
- **Numbers.** Agents may restate numbers written in the brief. If such a number is
  unsourced, the Editor's `untraced_number` check lists it in the dossier, as a code span.
  The acceptance check is `undisclosed_untraced(plan, markdown) == []`.
- **Not checked as figures:**
  - URLs and dates (ISO dates; bare years 1900–2099)
  - small structural integers (counts, months 1–12, the 30/60/90 plan, "first 100
    customers")
  - inline code spans
  
  A bare four-digit count that looks like a year also passes. That trade-off is accepted
  and documented in `services/trace.py`.
- **Channel vocabulary.** GTM and Finance pick channels from one fixed vocabulary
  (`ChannelType`), so the Editor's CAC check compares the same channel, not two spellings
  of it.
- **Scenarios.** Bear and bull are fixed multipliers in code (`finance.SCENARIOS`), the same
  for every plan, and are printed in the appendix.
- **PDF rendering is locked down:**
  - Markdown → HTML with `markdown-it-py` (CommonMark plus tables, raw HTML off).
  - WeasyPrint with a fetcher that serves only the bundled font files: no network, no
    other `file://` paths, so an image link in model text can't make the server fetch
    anything.
  - Bundled Noto Sans (OFL) through `@font-face`, which needs a `FontConfiguration`, so
    output doesn't depend on system fonts.
  - Rendering runs in a thread (about 1 s).
- **Pango missing.** `export?format=pdf` returns `503 pdf_unavailable`. WeasyPrint is
  imported lazily, so the rest of the API still runs.

## Consequences
- **Phase 7 Dockerfile:** must install Pango (`libpango-1.0-0`, `libpangoft2-1.0-0`).
- **Local macOS:** needs `brew install pango`. The uv Python only finds it through
  `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`, which SIP strips from `/bin/sh`, so the
  Makefile sets it inline per recipe. Tests that render PDFs skip on macOS when Pango
  isn't loadable, and fail elsewhere.
- **Failed sections fail the run.** A Phase-2 agent that never produces valid output fails
  the run (`run_failed`). The checkpoint keeps the sections that did complete, but there's
  no "retry Phase 2" action yet.
- **Versions.** Plans are versioned, but only v1 is written. Regenerating or editing a plan
  is future work.
- **Contradictions grow.** Real models estimating CAC independently in parallel will often
  disagree. Those disagreements are listed as contradictions, by design; reconciling them
  is the founder's call.
- **Scanner limits.** The scanner can't tell which figure a number was meant to quote, only
  that some registered figure has that value. A coincidental match passes.
