---
phase: 03-smart-iteration
plan: "05"
subsystem: hunt-orchestrator
tags:
  - hunt
  - autonomous-loop
  - orchestrator
  - fsa
  - selfcorr
  - editor
dependency_graph:
  requires:
    - 03-01  # editor.py (classify_from_checks, diagnose_and_mutate with stub pre-insert)
    - 03-02  # selfcorr.py (backfill_active_pnl, proxy gate)
    - 03-03  # fsa.py (mine_frequent_motifs, filter_candidates, diversity_metric)
    - 03-04  # grade.py (grade_many with max_workers, db_path, parent_alpha_id)
  provides:
    - hunt.hunt() — autonomous research→generate→grade→edit→loop orchestrator
    - /hunt Claude Code command
    - /iterate Claude Code command
  affects:
    - cli.py (pattern mirrored: single-shot auth, 401 surface, argparse)
tech_stack:
  added: []
  patterns:
    - D-16 bounded loop (depth OR budget OR dry-no-NEAR)
    - D-17 hard sim ceiling (max_sims=30 default)
    - D-20 best-of ranking by Sharpe
    - _is_passable() dedup filter (permits queued stubs from editor path)
    - diversity_metric before/after snapshot (criterion 4)
key_files:
  created:
    - hunt.py
    - .claude/commands/hunt.md
    - .claude/commands/iterate.md
  modified: []
decisions:
  - "_rank_best ranks by Sharpe descending (D-20 — primary ranking metric, Claude discretion)"
  - "_is_passable() replaces blanket db.expr_exists is None check — permits pre-inserted editor stubs (status=queued) through to grade_many without dropping 100% of mutations"
  - "hunt() function contains no login/auth reference — auth confined to CLI layer (CLAUDE.md)"
  - "selfcorr.backfill_active_pnl called once before loop, sequentially (not in sim pool)"
metrics:
  duration: "~20 min"
  completed: "2026-06-10"
  tasks_completed: 2
  tasks_total: 2
  files_created: 3
  files_modified: 0
---

# Phase 03 Plan 05: Hunt Orchestrator Summary

**One-liner:** hunt.py implements the D-16/D-17/D-20 bounded loop (research→generate→grade→edit→loop) with _is_passable() dedup fix and diversity_metric snapshots, plus /hunt and /iterate Claude Code commands.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | hunt.py autonomous loop orchestrator | f4d42be | hunt.py |
| 2 (pre-checkpoint) | .claude/commands/hunt.md + iterate.md | 89e5578 | .claude/commands/hunt.md, .claude/commands/iterate.md |

## What Was Built

### hunt.py

Full orchestrator implementing the Phase 3 headline deliverable:

- **Gen 0:** `selfcorr.backfill_active_pnl` (once, sequential) → `fsa.mine_frequent_motifs` → `researcher.build_thesis(avoid_motifs=...)` → `ideator.generate_candidates` → `fsa.filter_candidates` → `ideator.queueable` → `grade.grade_many(max_workers=3, db_path=db_path)`
- **Loop (range(max_depth)):** `editor.classify_from_checks` per result → accumulate pass/near → `editor.diagnose_and_mutate(avoid_motifs=...)` for near/fail → `_is_passable()` filter → `fsa.filter_candidates` → `grade.grade_many`
- **Stop conditions (D-16):** `sims_used >= max_sims` OR `not near_ids` OR `not queue_next`
- **Diversity snapshots:** `fsa.diversity_metric(conn)` captured before first grade_many and after final generation
- **Return:** `{best_submittable, best_near, sims_used, run_id, generations, diversity_before, diversity_after}`

### .claude/commands/hunt.md

Documents the /hunt command with: single-shot auth pattern, hunt.hunt() invocation with all flags, 401 handling code, stop condition explanation, flags table, auth/concurrency constraint warnings.

### .claude/commands/iterate.md

Documents the /iterate command with: DB query for NEAR/FAIL alphas, diagnose_and_mutate invocation, display pattern, optional grade_many queue, FSA steering guidance.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed 'login' keyword from hunt() function docstring**
- **Found during:** Task 1 verification (`python -c "assert 'login' not in inspect.getsource(hunt.hunt)"`)
- **Issue:** Plan's verification check uses a simple string match for 'login' in hunt() source. Original docstring referenced "wq_login.login()" to document the caller contract, causing the assertion to fail.
- **Fix:** Replaced docstring reference with "auth must be done once at CLI layer" — preserves intent without triggering the string match.
- **Files modified:** hunt.py
- **Commit:** f4d42be

None of the other plan requirements required deviation.

## Key Decisions

1. **_is_passable() over blanket db.expr_exists check:** The plan explicitly required removing the blanket `[m for m in all_mutations if db.expr_exists(conn, m) is None]` filter. `editor.diagnose_and_mutate` pre-inserts every mutation as `status='queued'`, so a blanket check would drop 100% of editor-returned mutations. `_is_passable()` instead permits expressions that are absent OR present with `status='queued'`.

2. **Final reclassification pass:** Added a post-loop reclassification of `results` from the last generation to catch any final PASS alphas before the best-of ranking. This ensures the `best_submittable` return includes alphas from all generations including the last one.

3. **`gen` variable initialization:** Set `gen = -1` before the loop so `generations: gen+1` returns 0 when `max_depth=0` rather than raising `UnboundLocalError`.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced. hunt.py delegates all BRAIN API calls to `grade.grade_many` and `selfcorr.backfill_active_pnl` (both already have threat mitigations from plans 03-02 and 03-04). T-03-14 through T-03-SC verified as mitigated per plan threat model.

## Checkpoint State

Checkpoint (Task 2, human-verify) APPROVED by user on 2026-06-10. All verification commands passed: import OK, no login inside hunt(), no blanket dedup filter. Plan complete.

## Self-Check

- [x] hunt.py exists at worktree root
- [x] .claude/commands/hunt.md exists
- [x] .claude/commands/iterate.md exists
- [x] hunt.py imports cleanly (`import hunt`)
- [x] hunt() function contains no 'login' string
- [x] Blanket db.expr_exists dedup filter absent
- [x] All plan structure checks pass (`hunt.py structure: PASS`)
- [x] Both task commits exist (f4d42be, 89e5578)

## Self-Check: PASSED
