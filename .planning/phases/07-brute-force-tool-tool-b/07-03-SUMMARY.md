---
phase: 07-brute-force-tool-tool-b
plan: "03"
subsystem: bruteforce-engine
tags: [bruteforce, engine, tdd, additivity, quota, 401-stop]
dependency_graph:
  requires: [07-01, 07-02]
  provides: [07-04]
  affects: [bruteforce.py, test_phase7.py]
tech_stack:
  added: []
  patterns:
    - ThreadPoolExecutor(max_workers=3) + as_completed for quota-aware bulk-sim
    - Per-template additivity gate reusing Phase 6 rank_by_proxy / confirm_additive
    - hit_401 propagation via return dict (not exception re-raise) from _bulk_sim_quota_aware
key_files:
  created: []
  modified:
    - test_phase7.py
decisions:
  - "Patched bruteforce.db.init_db to return a shared real_conn in tests so the main engine and assertions use the same in-memory DB (worker connections would otherwise open isolated :memory: DBs)"
  - "Patched bruteforce._bulk_sim_quota_aware directly for quota/401 tests instead of grade.grade_one — avoids threading complications with :memory: DBs across workers"
  - "test_probe_abandon uses redirect_stdout to capture 'template abandoned after probe' print without side effects"
metrics:
  duration: "~10 minutes"
  completed: "2026-06-16"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 1
---

# Phase 7 Plan 03: Bruteforce Engine Tests Summary

Append 5 engine tests to test_phase7.py covering BF-03/BF-04/BF-05/BF-06 — probe-abandon, validate-gate, quota-stop, 401-clean-stop, and per-template failure persistence.

## What Was Built

**Task 2 (703d4a8): 5 engine tests appended to test_phase7.py**

The existing 5 tests from Plans 07-01/07-02 were untouched. 5 new tests added at the bottom:

| Test | Covers | Key assertion |
|------|--------|---------------|
| `test_probe_abandon` | BF-03 / D-05 | all probe sims fail → "template abandoned after probe" printed, n_simmed==0 |
| `test_validate_gate_drops_combos` | BF-02 (engine) | validate always False → grade_one/grade_many never called, failure_counts["validate_dropped"] > 0 |
| `test_quota_stop` | BF-04 / D-07 | quota=1 + 2 templates → stops after 1st template yields 1 additive survivor |
| `test_401_stop` | D-09 | _bulk_sim_quota_aware returns hit_401=True → sys.exit(1) + partial=1 in DB |
| `test_bruteforce_runs_row_per_template` | BF-06 / D-11 | 2 templates → 2 rows with valid JSON failure_counts and examples |

All 10 tests in test_phase7.py pass (`10 passed in 0.06s`).

## Decisions Made

**Patch `bruteforce.db.init_db` to return a shared real_conn**

Tests that need to inspect DB state (validate_gate_drops_combos, 401_stop, bruteforce_runs_row_per_template) patch `bruteforce.db.init_db` to return a pre-created in-memory `real_conn`. This gives the test a handle to the same connection the engine uses for inserts, so `SELECT` assertions can verify rows without a file-path DB.

**Patch `bruteforce._bulk_sim_quota_aware` for quota/401 tests**

The internal `_bulk_sim_quota_aware` function opens per-worker connections via `db.init_db(db_path)`. In tests with `:memory:`, each worker's `init_db(":memory:")` would open an isolated empty DB. Patching `_bulk_sim_quota_aware` directly avoids threading complexity while still testing the engine's quota/401 logic at the `bruteforce()` / `_run_template()` level.

**`test_probe_abandon` uses `redirect_stdout`**

The plan spec required verifying the "template abandoned after probe" print. Used `contextlib.redirect_stdout` to capture stdout without mocking `sys.stdout` globally.

## Deviations from Plan

None. Plan executed exactly as written.

The plan spec said to use `template_names=["residual_momentum"]` for probe_abandon (all-literal slots). `residual_momentum` has `fast` and `slow` literal slots (3x3 = 9 combos) — confirmed correct for test setup.

## Self-Check

- [x] 10 tests pass: `test_bruteforce_runs_schema`, `test_template_enumeration`, `test_slot_expansion`, `test_validate_gate`, `test_probe_spread_sample`, `test_probe_abandon`, `test_validate_gate_drops_combos`, `test_quota_stop`, `test_401_stop`, `test_bruteforce_runs_row_per_template`
- [x] Existing 5 tests from 07-01/07-02 untouched (verified by line count: 329 → 657 lines)
- [x] No modifications to bruteforce.py, STATE.md, or ROADMAP.md
- [x] Commit 703d4a8 exists with 1 file changed (+328 lines)

## Known Stubs

None.

## Threat Flags

None — test file only; no new network endpoints, auth paths, or schema changes.
