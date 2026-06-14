---
phase: 04-optimization-polish
plan: 03
subsystem: optimizer
tags: [optimizer, settings-tuning, archetype-heuristics, grade_many, parent_alpha_id]

# Dependency graph
requires:
  - phase: 04-01
    provides: "grade.py settings override (grade_many settings_map param), db.py checks_history + note_path"
  - phase: 03
    provides: "selfcorr.proxy_gate, grade.grade_many, db.upsert_alpha"
provides:
  - "optimizer.py: ARCHETYPE_HEURISTICS constant, build_variants(), run_optimize()"
  - "optimize.py: /optimize CLI entrypoint with single-shot BRAIN auth"
affects:
  - "04-04 (decay monitor may import optimizer)"
  - "04-05 (obsidian.regen_all is called by run_optimize)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Archetype heuristic table: ARCHETYPE_HEURISTICS maps 8 researcher.ARCHETYPES labels to (decay,neutralization,truncation) tuples"
    - "Settings variant builder: heuristic candidates + past PASS/ACTIVE combos from DB, deduplicated, capped at 4"
    - "Optional conn parameter: run_optimize accepts conn= for test injection; grade_many uses db_path for thread-safe worker connections"
    - "obsidian graceful degrade: try import obsidian; if unavailable, log warning and skip regen"

key-files:
  created:
    - optimizer.py
    - optimize.py
  modified: []

key-decisions:
  - "run_optimize accepts optional conn= parameter for test injection while grade_many workers use db_path for thread safety (tests pass in-memory DB directly)"
  - "obsidian import guarded with try/except so optimizer works before obsidian.py is implemented (04-05)"
  - "Sequential variant simulation (max_workers=1 per variant) because each variant has different settings; BRAIN concurrency cap enforced by grade_many"
  - "proxy_gate called once per NEAR alpha before the variants loop — gate checks the NEAR alpha parent itself, not each variant's expression"

patterns-established:
  - "Archetype heuristic table: define 8 archetypes x 4 (d,n,t) tuples; NULL archetype defaults to reversal"
  - "CLI entrypoint mirrors hunt.py: single-shot login, EditorAuthError handler, HTTPError 401 handler, argparse with --db and --max-workers"

requirements-completed:
  - OPT-01

# Metrics
duration: 15min
completed: 2026-06-11
---

# Phase 4 Plan 03: Settings Optimizer Summary

**ARCHETYPE_HEURISTICS table (8 archetypes x 4 tuples) + build_variants() blending heuristics with past PASS settings + run_optimize() calling grade_many with settings_map/parent_map for variant lineage recording**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-06-11T05:30:00Z
- **Completed:** 2026-06-11T05:45:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- ARCHETYPE_HEURISTICS constant covering all 8 researcher.ARCHETYPES labels (reversal, momentum, value_garp, quality, growth, low_volatility, liquidity_volume, sentiment_event), each with 4 (decay,neutralization,truncation) tuples derived from WorldQuant BRAIN parameter mechanics
- build_variants() merging heuristic candidates with past PASS/ACTIVE settings from DB, deduplicating by (d,n,t) tuple, capping at 4, and building full settings dicts (preserving region/universe/delay per D-01)
- run_optimize() orchestrating the full NEAR alpha => proxy_gate => build_variants => grade_many loop with parent_map and settings_map for DB lineage recording, plus obsidian.regen_all() side-effect (D-11)
- optimize.py CLI mirroring hunt.py pattern: single-shot login, EditorAuthError + 401 handlers, summary printout

## Task Commits

Each task was committed atomically:

1. **Task 1: ARCHETYPE_HEURISTICS + build_variants** - `9be769f` (feat)
2. **Task 2: run_optimize orchestrator + optimize.py CLI** - `eea84f1` (feat)

## Files Created/Modified
- `optimizer.py` — ARCHETYPE_HEURISTICS, build_variants, run_optimize
- `optimize.py` — /optimize CLI entrypoint

## Decisions Made
- run_optimize accepts optional `conn=` parameter: tests pass in-memory connections directly; production path opens conn from db_path. grade_many workers still use db_path for their own per-thread connections (SQLite thread safety).
- obsidian import is guarded with `try/except ImportError`: run_optimize works before obsidian.py exists (plan 04-05). If obsidian is unavailable, logs a warning and continues.
- proxy_gate is called once per NEAR alpha (before build_variants), not per variant. This is correct: the gate checks the NEAR alpha's own PnL correlation, not each variant's expression.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree required reset to ffc3eee base commit**
- **Found during:** Task 1 setup
- **Issue:** Worktree HEAD was at d2d4665 (Phase 3), missing test_phase4.py and Phase 4 files (db.py schema extensions, grade.py settings param). The worktree_branch_check detected merge-base mismatch.
- **Fix:** `git reset --hard ffc3eee54c19140bd8b4b639301eaac54fb38389` to sync worktree to Phase 4 wave-1-complete baseline as specified in the prompt.
- **Files modified:** All Phase 4 files restored (db.py, grade.py, test_phase4.py, etc.)
- **Verification:** test_phase4.py present after reset; all OPT-01 tests moved from SKIP to PASS

---

**Total deviations:** 1 auto-fixed (1 blocking - worktree base reset)
**Impact on plan:** Necessary infrastructure fix; no scope change.

## Issues Encountered
- None beyond the worktree base reset documented above.

## Known Stubs
None — optimizer.py and optimize.py are fully wired.

## Threat Flags
None — no new network endpoints, auth paths, or schema changes introduced. ARCHETYPE_HEURISTICS is a read-only constant; all SQL queries use ? parameterized form.

## Next Phase Readiness
- optimizer.py and optimize.py ready for integration
- obsidian.regen_all() is called as a side-effect but guarded: plan 04-05 must implement obsidian.py for the D-11 side-effect to be active
- decay_monitor.py (04-04) and obsidian.py (04-05) can be developed in parallel — no dependencies on this plan beyond db.py schema (already in 04-01)

---
*Phase: 04-optimization-polish*
*Completed: 2026-06-11*
