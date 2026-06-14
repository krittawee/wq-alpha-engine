---
phase: quick-260611-l3w
plan: "01"
subsystem: grading
tags: [grade, settings-fidelity, db-correction, test]
dependency_graph:
  requires: []
  provides: [GRADE-SETTINGS-FIDELITY]
  affects: [grade.py, alpha_kb.db, test_phase4.py]
tech_stack:
  added: []
  patterns: [BRAIN-wins-over-request, brain_settings-fallback-pattern]
key_files:
  created: []
  modified:
    - grade.py
    - test_phase4.py
decisions:
  - "Resolved all 6 settings fields via brain_settings.get(field, active_settings.get(field)) — BRAIN wins, requested settings are fallback"
  - "settings_json built from the 6 resolved fields only (not full active_settings) — consistent with column values"
  - "Test patches trigger_correlation_check and poll_correlation to avoid the 300s timeout — cleaner than setting is_survivor=False"
metrics:
  duration: ~12min
  completed: 2026-06-11
  tasks: 3
  files_modified: 2
---

# Phase quick-260611-l3w Plan 01: grade_one BRAIN Settings Fidelity Fix Summary

**One-liner:** grade_one now reads BRAIN's returned settings dict via `alpha.get("settings")`, persisting what BRAIN actually ran (e.g., delay coerced 0→1) rather than the requested settings.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Read BRAIN's returned settings from alpha dict in grade_one | 4bff017 | grade.py |
| 2 | Correct 11 stale alpha_kb.db rows (delay 0 → 1) | (not committed — gitignored) | alpha_kb.db |
| 3 | Unit test — grade records BRAIN's returned settings, not requested settings | b70c3fd | test_phase4.py |

## Task 1: grade.py Fix

**What changed:** Step 5 in `grade_one` (lines ~186-204) was rewritten to extract `brain_settings = alpha.get("settings") or {}` from the BRAIN-returned alpha dict. Each of the 6 persisted fields (region, universe, delay, decay, neutralization, truncation) is resolved as `brain_settings.get(field, active_settings.get(field))`. `settings_json` is built from the 6 resolved values.

**Before:**
```python
active_settings = settings if settings is not None else _BASE_SETTINGS
settings_json = json.dumps(active_settings)
# ... used active_settings["delay"], active_settings["region"], etc.
```

**After:**
```python
active_settings = settings if settings is not None else _BASE_SETTINGS
brain_settings = alpha.get("settings") or {}
resolved_delay = brain_settings.get("delay", active_settings.get("delay"))
# ... same pattern for all 6 fields
settings_json = json.dumps({6-field dict of resolved values})
# ... alpha_dict uses resolved_delay, resolved_region, etc.
```

## Task 2: DB Correction (alpha_kb.db — NOT in git, gitignored)

All 11 stale rows had `delay=0` in both the `delay` column and `settings_json`. BRAIN's authoritative value is `delay=1` for all 11 (known from pre-diagnosis; no BRAIN API called).

### Before state (all 11 rows):

```
1Ygw09oz: col_delay=0, sj_delay=0
6XEloQY7: col_delay=0, sj_delay=0
A13lmvqw: col_delay=0, sj_delay=0
GrolxOpZ: col_delay=0, sj_delay=0
MPx7ZExM: col_delay=0, sj_delay=0
QPQ7zqjG: col_delay=0, sj_delay=0
mLXj0GRp: col_delay=0, sj_delay=0
mLXj0lGX: col_delay=0, sj_delay=0
omYqGpdk: col_delay=0, sj_delay=0
omYqrXrk: col_delay=0, sj_delay=0
qMXj30AO: col_delay=0, sj_delay=0
```

### After state (all 11 rows):

```
1Ygw09oz: col_delay=1, sj_delay=1
6XEloQY7: col_delay=1, sj_delay=1
A13lmvqw: col_delay=1, sj_delay=1
GrolxOpZ: col_delay=1, sj_delay=1
MPx7ZExM: col_delay=1, sj_delay=1
QPQ7zqjG: col_delay=1, sj_delay=1
mLXj0GRp: col_delay=1, sj_delay=1
mLXj0lGX: col_delay=1, sj_delay=1
omYqGpdk: col_delay=1, sj_delay=1
omYqrXrk: col_delay=1, sj_delay=1
qMXj30AO: col_delay=1, sj_delay=1
```

### Verification query output:

```
All 11 rows verified delay=1 in column and settings_json
```

Script: `/tmp/fix_delay.py` — pure sqlite3, no BRAIN API calls.

**alpha_kb.db changes are NOT in git** (file is gitignored). All 11 rows were verified corrected by the plan's verification query.

## Task 3: New Test

`test_grade_records_brain_actual_settings` in `test_phase4.py`:
- Configures mock BRAIN response with `"settings": {"delay": 1, ...}` while passing `settings={"delay": 0, ...}` (the REQUEST).
- After `grade_one` completes, asserts `delay` column == 1 and `settings_json["delay"]` == 1.
- Patches: `validate.validate`, `selfcorr.proxy_gate`, `selfcorr.fetch_and_cache_pnl`, `grade.trigger_correlation_check`, `grade.poll_correlation` — zero BRAIN API calls, runs in 0.08s.

## Test Results

```
24 passed, 6 warnings in 0.10s
```

All tests green. No regressions.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test mock missing validate patch and Phase B patches**

- **Found during:** Task 3 (first test run)
- **Issue:** `validate.validate` rejected `"close / open"` (unknown data field `close`), causing `grade_one` to return early with `status=invalid` before inserting any DB row. Additionally, the is_survivor=True path calls `poll_correlation` with a 300s timeout — the un-patched MagicMock response caused a 300s hang.
- **Fix:** Added `patch("validate.validate", return_value=(True, None))`, `patch("grade.trigger_correlation_check", return_value=None)`, and `patch("grade.poll_correlation", return_value={})` to the test context manager.
- **Files modified:** test_phase4.py
- **Commit:** b70c3fd (included in same Task 3 commit)

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced.

## Self-Check

- [x] grade.py committed: 4bff017
- [x] test_phase4.py committed: b70c3fd
- [x] alpha_kb.db corrected and verified (not committed — gitignored)
- [x] Full suite green: 24 passed in 0.10s

## Self-Check: PASSED
