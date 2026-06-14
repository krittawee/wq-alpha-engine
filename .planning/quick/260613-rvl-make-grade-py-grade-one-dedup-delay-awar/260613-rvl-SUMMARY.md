---
phase: quick-260613-rvl
plan: 01
status: complete
subsystem: grade
tags: [dedup, delay-aware, bug-fix, regression-test]
dependency_graph:
  requires: []
  provides: [BUG-5-dedup-delay-blind]
  affects: [grade.py, test_phase4.py]
tech_stack:
  added: []
  patterns: [delay-aware-dedup, offline-mock-testing]
key_files:
  modified:
    - grade.py
    - test_phase4.py
decisions:
  - "delay-BLIND db.expr_exists call preserved intentionally (stubs have NULL delay); delay comparison applied only to non-queued rows"
  - "effective_delay derived from active_settings.get('delay', delay) — caller-supplied settings dict wins, consistent with existing precedence logic"
  - "_simulate_to_alpha patch strategy used (not client.simulate) — cleanest isolation since function exists at grade.py:203"
metrics:
  duration: "~10 min"
  completed: "2026-06-13"
  tasks: 2
  files: 2
---

# Quick Task 260613-rvl: Make grade.py grade_one Dedup Delay-Aware — Summary

**One-liner:** Patched grade_one Step-0 to compare stored vs effective delay before declaring duplicate, preventing cross-delay false-skips; added three offline regression tests.

## What Was Built

**Task 1 — grade.py Step-0 patch:**

The Step-0 dedup block in `grade_one` was delay-blind: it called `db.expr_exists(conn, expression)` (no delay arg) and immediately returned `{"status": "duplicate"}` if the found row was non-queued — regardless of whether that row had a different delay. This caused 4/5 delay-0 candidates to be skipped on 2026-06-13 because they existed at delay-1.

Fix applied (Option A from diagnosis):
- Added `effective_delay = active_settings.get("delay", delay)` before Step-0 (after `active_settings` is set)
- Extended the SELECT to fetch `delay` column: `SELECT status, parent_alpha_id, delay FROM alphas WHERE alpha_id=?`
- Non-queued branch now only returns `"duplicate"` when `stored_delay == effective_delay`
- When delays differ: `existing_id = None` (fall through as novel; no stub_id_to_replace set)
- `db.expr_exists` call remains delay-BLIND (stubs have NULL delay — delay-aware query would miss them)
- Queued stub path restructured into explicit `else` branch (behavior unchanged)

**Task 2 — three offline regression tests in test_phase4.py:**

- `test_grade_dedup_cross_delay_not_duplicate` — delay=0 call with existing delay=1 row: asserts not duplicate, `_simulate_to_alpha` called
- `test_grade_dedup_same_delay_is_duplicate` — delay=1 call with existing delay=1 row: asserts duplicate with correct alpha_id, `_simulate_to_alpha` NOT called
- `test_grade_dedup_queued_stub_inherited` — delay=0 call with queued stub (NULL delay): asserts not duplicate, simulate called, parent_alpha_id="PARENT01" inherited in persisted row

Helper `_make_sim_alpha(alpha_id, delay)` added above the test functions to produce well-formed `(sim_mock, alpha_dict)` tuples that pass grade_one's full persist path without errors.

## Verify Results

```
Task 1 verify:
grade imports OK

Task 2 verify (three new tests):
3 passed in 0.07s

Full suite:
33 passed, 18 warnings in 0.08s

Caller compatibility:
all callers import OK

Import smoke:
imports OK
```

**Final pytest result line:** `33 passed, 18 warnings in 0.08s`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Queued stub else-branch needed explicit restructuring**
- **Found during:** Task 1
- **Issue:** The original code had `if row is None or row[0] != "queued": ... return` with lineage inheritance falling through implicitly. Adding the delay comparison required an explicit `else:` branch for the queued path to keep the logic clean and correct.
- **Fix:** Added explicit `else:` block for queued stub path; behavior is identical to original.
- **Files modified:** grade.py

**2. [Rule 1 - Bug] Test mocks needed proper sim/alpha return types**
- **Found during:** Task 2
- **Issue:** Initial `_simulate_to_alpha` mock returned `(MagicMock(), {...})`. The `MagicMock().alpha_id` is a MagicMock object, not a string, causing `sqlite3.ProgrammingError: Error binding parameter 1: type 'MagicMock' is not supported` when grade_one tried to upsert the result.
- **Fix:** Extracted `_make_sim_alpha(alpha_id, delay)` helper that builds a well-formed `(mock_sim, alpha_dict)` with string alpha_id and full settings dict (including matching delay to avoid D-03 coercion discard path).
- **Files modified:** test_phase4.py

## Known Stubs

None.

## Threat Flags

None — changes confined to internal grade_one Step-0 dedup logic; no new network surface or trust boundary crossings.

## Self-Check

- [x] grade.py modified and imports OK
- [x] test_phase4.py has three new test functions
- [x] All 33 tests pass (0 failures)
- [x] Caller imports (find_alphas, hunt, grade) OK
- [x] Full import smoke (db, editor, grade, find_alphas, ideator, selfcorr, hunt, validate) OK
- [x] 401 propagation preserved (not touched)
- [x] D-03 coercion warn+discard preserved (not touched)
- [x] delay-blind db.expr_exists preserved (intentional)
- [x] Queued stub NULL-delay inheritance path works (test c passes)
