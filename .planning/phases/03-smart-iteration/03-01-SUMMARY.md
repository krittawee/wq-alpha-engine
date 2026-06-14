---
phase: 03-smart-iteration
plan: "01"
subsystem: editor
tags: [editor, classification, mutation, llm-tier, db-schema]
dependency_graph:
  requires: [db.py, validate.py]
  provides: [editor.py classify_from_checks, editor.py diagnose_and_mutate, db.py diagnosis column]
  affects: [hunt.py plan-05, grade.py plan-04, test_phase3.py]
tech_stack:
  added: []
  patterns: [hybrid-deterministic-llm, subprocess-claude-cli, validate-gate-before-insert, parameterized-sql, tdd-red-green]
key_files:
  created:
    - editor.py
    - test_phase3.py
  modified:
    - db.py
decisions:
  - "stub-<uuid8> alpha_id for mutation pre-inserts so expr_exists can detect queued mutations (alpha_id=None breaks duplicate detection)"
  - "subprocess claude --print --output-format text for LLM tier (no existing subprocess pattern in codebase; mirrors researcher.py hybrid intent)"
  - "PENDING filter applied before hard-fail check (PENDING rows have None value/limit which would cause false hard-fail on name-only matching)"
metrics:
  duration: "390s"
  completed: "2026-06-10"
  tasks_completed: 3
  files_changed: 3
---

# Phase 3 Plan 1: Editor Module (classify + diagnose + mutate) Summary

**One-liner:** Hybrid Editor with deterministic PASS/NEAR/FAIL classification (HARD_FAIL_CHECKS frozenset, EPSILON=0.01, D-07 cap) and LLM mutation tier via subprocess Claude CLI with validate+dedup gate and stub-id pre-insert lineage.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 (RED) | Failing tests for classify_from_checks + db diagnosis column | a3fd6ae | test_phase3.py |
| 1 (GREEN) | editor.py classify_from_checks + diagnose_and_mutate | b7f3861 | editor.py, test_phase3.py |
| 3 | db.py diagnosis TEXT column + idempotent ALTER TABLE | 48c72e9 | db.py |
| Dev | Rule 1 stub_id fix for expr_exists duplicate detection | 6bc7365 | editor.py |

## What Was Built

### editor.py

- `HARD_FAIL_CHECKS = frozenset({"MATCHES_COMPETITION", "CONCENTRATED_WEIGHT"})` — module-level constant
- `EPSILON = 0.01` — denominator floor for near-zero limit_val (LOW_SUB_UNIVERSE_SHARPE edge case)
- `classify_from_checks(alpha_id, conn)` — deterministic PASS/NEAR/FAIL:
  1. Parameterized SELECT from checks; filter PENDING rows
  2. Hard-fail gate: any HARD_FAIL_CHECKS member → return ("fail", [name]) immediately
  3. Numeric fails: gap = abs(val-lim)/max(abs(lim), EPSILON)
  4. No numeric_fails → ("pass", [])
  5. ≤2 fails AND all gap ≤ 20% → ("near", [names])
  6. Otherwise → ("fail", [names])
- `_build_editor_context(...)` — assembles structured plain-text prompt with IS metrics, failing checks, diagnosis + mutation request
- `_call_llm_editor(context)` — subprocess `claude --print --output-format text`; strips markdown fences; parses JSON
- `diagnose_and_mutate(alpha_id, conn, avoid_motifs=None)`:
  - Calls classify_from_checks; early-return for "pass"
  - LLM call → validate.validate + db.expr_exists gate (D-03)
  - PRE-INSERTS stubs with `alpha_id="stub-<uuid8>"`, `parent_alpha_id=alpha_id`, `status="queued"` before returning
  - Writes `diagnosis` to source alpha via `UPDATE alphas SET diagnosis=? WHERE alpha_id=?`
  - 401 propagation (CLAUDE.md constraint); graceful degrade on other errors

### db.py changes

- `diagnosis TEXT` added to CREATE TABLE IF NOT EXISTS alphas DDL (after `pnl_path`)
- `"diagnosis"` inserted in `_ALPHA_COLS` list (after `"pnl_path"`)
- Idempotent ALTER TABLE migration in `init_db()` — upgrades existing Phase 1/2 databases; catches `sqlite3.OperationalError` for re-entrant calls

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed alpha_id=None in mutation pre-inserts breaking expr_exists**
- **Found during:** Task 2 implementation review
- **Issue:** `alpha_id=None` stored as primary key; `expr_exists()` returns `row[0]` which is `None` — grade_one would NOT detect the stub as a duplicate and would re-simulate it
- **Fix:** Generate `stub-<uuid8>` placeholder alpha_id for each mutation stub; real BRAIN alpha_id written by grade_one after simulation
- **Files modified:** editor.py
- **Commit:** 6bc7365

**2. [Rule 3 - Blocking] Tests used shutil.copy("alpha_kb.db") which fails in worktree**
- **Found during:** Task 1 RED verification
- **Issue:** Worktree cwd lacks alpha_kb.db (lives in main repo checkout)
- **Fix:** Added `_make_test_db()` helper that uses `shutil.copy` when file exists, falls back to fresh db.init_db() otherwise — tests self-contained
- **Files modified:** test_phase3.py
- **Commit:** b7f3861 (included in GREEN commit)

## TDD Gate Compliance

- RED gate: commit a3fd6ae (test: prefix, 8 failing tests)
- GREEN gate: commit b7f3861 (feat: prefix, 7/8 tests pass; 8th passes after db.py Task 3)
- Task 3 (db.py) committed separately: commit 48c72e9 — all 8 tests pass after this commit

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes beyond what is in the plan's threat_model. The `subprocess.run(["claude", ...])` call has no new network surface exposed by this module (Claude CLI manages its own auth). The diagnosis TEXT column is append-only and not exposed outside the SQLite boundary.

## Known Stubs

None. All functions are implemented. The LLM tier has graceful degrade (returns `diagnosis=None, mutations=[]` on failure) which is intentional, not a stub.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| editor.py | FOUND |
| test_phase3.py | FOUND |
| 03-01-SUMMARY.md | FOUND |
| commit a3fd6ae (test RED) | FOUND |
| commit b7f3861 (feat GREEN) | FOUND |
| commit 48c72e9 (db.py) | FOUND |
| commit 6bc7365 (fix stub_id) | FOUND |
| All 8 tests pass | VERIFIED |
