# AutoIncubator

AI venture studio: discover → stress-test → co-work → full business plan.

## How this repo is driven with Claude

| File | Role | Changes |
|---|---|---|
| `CLAUDE.md` | Permanent rules: stack, layout, code rules, commands. Auto-loaded by Claude Code. | Rarely |
| `docs/SPEC.md` | What the product is and its architecture. | Rarely, through an ADR |
| `docs/phases/NN-*.md` | One build phase each: scope, acceptance criteria, ready-to-paste prompt. | Before each phase |
| `docs/PROGRESS.md` | Claude's log of what was built and what's next. This is the memory between sessions. | Every phase |
| `docs/decisions/` | ADRs for non-obvious choices. | As needed |
| `docs/ORIGINAL_PROMPT.md` | The full one-shot prompt, kept for reference only. Don't feed it to Claude. | Never |

## Workflow per phase
1. Start a **fresh** Claude Code session in the repo root.
2. Paste the "Prompt to paste" block from the current phase file.
3. Review Claude's plan. Push back, then approve.
4. Let it build. It runs the acceptance checks and updates `PROGRESS.md`.
5. Check the acceptance criteria yourself (run the app), then commit and tag `phase-N`.
6. Next phase: new session.

Tips:
- Use plan mode (Shift+Tab in Claude Code) for the planning step of each phase.
- If a phase gets too long, ask Claude to stop at a clean point and log it in `PROGRESS.md`. The next session picks up from there.
- Edit a phase file before starting it if your priorities change. The phase files are yours to shape.
