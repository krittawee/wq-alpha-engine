---
phase: 07-brute-force-tool-tool-b
plan: "01"
subsystem: db
tags: [sqlite, schema, crud, test-scaffold, bruteforce]
dependency_graph:
  requires: []
  provides:
    - db.insert_bruteforce_run
    - db.update_bruteforce_run
    - bruteforce_runs table
    - test_phase7.py scaffold
  affects:
    - bruteforce.py (Plan 07-03 depends on these CRUD functions)
    - test_phase7.py (Plans 07-02, 07-03 add tests here)
tech_stack:
  added: []
  patterns:
    - parameterized dynamic-column INSERT into SQLite (same as upsert_alpha)
    - per-test in-memory SQLite fixture (same as test_phase4.py)
key_files:
  created:
    - path: test_phase7.py
      note: Phase 7 test scaffold with fresh_db fixture, 3 make_mock_* helpers, 1 schema test
  modified:
    - path: db.py
      note: Added bruteforce_runs DDL (17-col table + run_id index) + insert_bruteforce_run + update_bruteforce_run
decisions:
  - "D-11 implemented: failure aggregates stored as JSON TEXT columns (failure_counts, examples) in bruteforce_runs, not one row per dead combo"
  - "insert_bruteforce_run uses plain INSERT (not INSERT OR REPLACE) so each template invocation gets a unique row even if run_id+template_name repeat"
  - "update_bruteforce_run silently drops unknown column keys (same safety pattern as insert) to avoid SQL injection via caller dict keys"
metrics:
  duration_seconds: 420
  completed_date: "2026-06-15"
  tasks_completed: 2
  files_changed: 2
---

# Phase 7 Plan 01: DB Schema and Test Scaffold Summary

**One-liner:** bruteforce_runs table (17 cols + run_id index) with dynamic-column INSERT/UPDATE CRUD and pytest scaffold for Phase 7 test suite

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | Add bruteforce_runs DDL + CRUD to db.py | d2550a8 | db.py |
| 2 | Create test_phase7.py scaffold with fixtures and schema test | 6c554df | test_phase7.py |

## What Was Built

**db.py additions:**

- `bruteforce_runs` table appended to `_DDL` list with all 17 columns per D-11 spec: `id` (AUTOINCREMENT PK), `run_id`, `template_name`, `delay`, `quota_target`, `n_combos`, `n_validated`, `n_probed`, `n_simmed`, `n_survivors`, `n_additive`, `quota_hit` (DEFAULT 0), `partial` (DEFAULT 0), `failure_counts` (TEXT), `examples` (TEXT), `started_at`, `finished_at`.
- `idx_bruteforce_runs_run` index on `run_id` also appended to `_DDL`.
- `_BRUTEFORCE_RUN_COLS` list for column filtering (same safety pattern as `_ALPHA_COLS`).
- `insert_bruteforce_run(conn, row) -> int`: dynamic col_list INSERT, returns `cur.lastrowid`, calls `conn.commit()`.
- `update_bruteforce_run(conn, rowid, updates) -> None`: `SET k=? WHERE id=?` patch, calls `conn.commit()`.

**test_phase7.py additions:**

- Module docstring per spec.
- `fresh_db()` pytest fixture: `db.init_db(':memory:')` with `yield` + `conn.close()`.
- `make_mock_grade_one_result(status, alpha_id)` plain function helper.
- `make_mock_classify_result(status)` plain function helper.
- `make_mock_additivity_result(additive, proxy_drop)` plain function helper returning MagicMock.
- `test_bruteforce_runs_schema(fresh_db)`: verifies table/index presence, insert row-id, read-back of all key columns (including JSON round-trip for failure_counts/examples), and update patch leaving other columns unchanged.

## Verification Results

```
1 passed in 0.01s   (pytest test_phase7.py -x -q)
(1,)                (SELECT COUNT(*) FROM sqlite_master WHERE name='bruteforce_runs')
2                   (grep function definitions for insert/update)
9                   (grep occurrences of 'bruteforce_runs' in db.py — min required: 3)
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. This plan is pure schema + CRUD + test scaffold with no UI rendering or data-display paths.

## Threat Flags

No new network endpoints, auth paths, file access patterns, or trust-boundary schema changes introduced beyond what the plan's threat model covers. T-07-01-01 mitigation is in place: column names come from `_BRUTEFORCE_RUN_COLS` filter (not raw caller dict keys), so unknown keys are silently dropped rather than executed as SQL.

## Self-Check: PASSED

- `/Users/winter.__.kor/quant/.claude/worktrees/agent-aaac4f662e633ac68/db.py` — exists, contains bruteforce_runs DDL and CRUD functions
- `/Users/winter.__.kor/quant/.claude/worktrees/agent-aaac4f662e633ac68/test_phase7.py` — exists, 152 lines, test passes
- Commit d2550a8 — verified in git log
- Commit 6c554df — verified in git log
