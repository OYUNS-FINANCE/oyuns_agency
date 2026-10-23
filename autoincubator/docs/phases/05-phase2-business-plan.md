# Phase 5 — Phase-2 agents, financial engine & dossier export

## Goal
After select, four agents produce a coherent, sourced business plan that I can read in the UI and export as Markdown and PDF.

## Scope
- **Agents 4–6** (Product Architect, GTM Strategist, Financial Modeler) run as a parallel fan-out; then the **Editor** runs as the fan-in. Each has its own prompt module and Pydantic schemas.
- **Financial engine** (`services/finance.py`): pure Python, no LLM.
  - The LLM provides an `AssumptionSet` (price tiers, conversion rates, churn, CAC per channel, costs).
  - The engine computes LTV, CAC, payback, gross margin, and 12-month MRR/cash/runway under base/bear/bull.
  - Fully unit-tested with hand-checked numbers.
- **Editor consistency checks** (code + LLM): GTM channel CAC must equal Finance CAC inputs, and MVP scope must match the Architect's build estimate. Contradictions are listed in the dossier rather than hidden.
- **Table:** `business_plans` (structured JSON + rendered Markdown + version).
- **Export:** `GET /plan/export?format=md|pdf`. Markdown renders from a Jinja template; PDF via WeasyPrint (or justify an alternative in an ADR). Includes the 30/60/90 checklist and the "Sources & Assumptions" appendix.
- **Frontend `/runs/[runId]/plan`:** section navigation, financial tables + charts (base/bear/bull toggle), contradiction callouts, export buttons.

## Acceptance criteria
- [ ] Finance engine tests pass against a hand-calculated reference case.
- [ ] Changing one assumption updates every dependent number (test).
- [ ] The full run with fakes reaches `completed`, and a plan exists.
- [ ] Every number in the dossier traces to a source, an assumption, or an engine calculation (automated check).
- [ ] The PDF renders correctly (open it and check: tables, Cyrillic/Mongolian text, page breaks).
- [ ] All checks are green; PROGRESS.md is updated.

## Prompt to paste
```
Phase 5. Read CLAUDE.md, docs/SPEC.md §5, docs/PROGRESS.md and docs/phases/05-phase2-business-plan.md.
Propose: the AssumptionSet schema, the finance engine formulas (written out), the Editor's consistency checks, and the dossier template outline. Wait for my OK, then implement — finance engine and its tests first — and verify every acceptance criterion.
```
