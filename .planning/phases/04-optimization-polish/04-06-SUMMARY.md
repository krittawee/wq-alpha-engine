# Plan 04-06 Summary — Phase Gate: /optimize + /decay commands + verification

**Plan:** 04-06 (Wave 3) — phase gate
**Status:** Complete
**Tasks:** 2/2 (Task 1 auto, Task 2 human-verify checkpoint — approved)

## What was built

Task 1 — created the two slash-command files that wire Phase 4's Python orchestrators
into Claude Code, mirroring the existing `/hunt` command structure exactly:

- `.claude/commands/optimize.md` — `/optimize` → `optimizer.run_optimize()` (settings
  optimizer over NEAR alphas + Obsidian note regen as a side-effect). Documents
  single-shot auth, `--db`/`--max-workers` flags, `max_workers=1` sequential variant
  sim, and the BRAIN concurrency/auth constraints.
- `.claude/commands/decay.md` — `/decay` → `decay_monitor.run_decay()` (re-checks live
  PASS/ACTIVE alphas, appends to `checks_history`, flags drops > threshold). Documents
  the no-data behavior (≥2 history points required) and `--db`/`--threshold` flags.

Both are flat `.md` files in `.claude/commands/` (not SKILL.md subdirectories). `/hunt`,
`/iterate`, `/find-alphas` were left unmodified (decision D-12).

## Verification (Task 2 checkpoint — all green)

- **Combined suite:** `pytest test_phase4.py test_phase3.py` → **23 passed, 0 failed**
  (12 Phase 4 + 11 Phase 3 — no regressions from the grade.py settings-param change).
- **Imports:** `optimizer`, `decay_monitor`, `obsidian` all import cleanly.
- **ROADMAP Criterion 1 (OPT-01):** `optimizer.build_variants` → 4 variants (≤4 ✓).
- **ROADMAP Criterion 2 (OPT-02):** `decay_monitor.detect_decay` → `{'status':'no_data','metric':None}` on fresh alpha ✓.
- **ROADMAP Criterion 3 (OPT-03):** `obsidian.regen_archetype_notes` → 8 notes (= len(ARCHETYPES)) ✓.

Human-verify checkpoint approved by user.

## Key files

- `.claude/commands/optimize.md` (created)
- `.claude/commands/decay.md` (created)

## Commits

- `feat(04-06): add /optimize and /decay command files`

## Notes / follow-ups

- Minor: `db.py:149` uses deprecated `datetime.utcnow()` — emits a DeprecationWarning,
  no functional impact. Candidate for a polish cleanup.
- Phase 4 delivered OPT-01/02/03 end-to-end. The settings-override hook added in 04-01
  (`grade.grade_one(settings=...)`) is the foundation for a future targeted-hunt feature
  (delay-0 + seed-from-submitted-alphas) requested post-phase.
