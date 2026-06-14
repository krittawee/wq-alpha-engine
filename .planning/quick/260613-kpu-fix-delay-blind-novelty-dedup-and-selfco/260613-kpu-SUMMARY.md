---
phase: quick-260613-kpu
plan: 01
status: complete
completed_at: "2026-06-13T07:03:02Z"
duration_seconds: ~300
tasks_completed: 3
files_changed: 5
subsystem: db / ideator / hunt / selfcorr / tests
tags: [bugfix, delay, dedup, selfcorr, pnl-parser, regression-tests]
requirements: [BUG-DELAY-DEDUP, BUG-SELFCORR-PNL]

dependency_graph:
  requires: []
  provides:
    - delay-aware db.expr_exists(conn, expression, delay=None)
    - delay-threaded ideator.generate_candidates(..., delay=None)
    - delay-passed hunt Gen 0 → generate_candidates
    - selfcorr._parse_pnl_response for schema+records BRAIN response
  affects:
    - hunt delay-0 runs (candidates no longer dropped as duplicates)
    - selfcorr PnL cache (now written with actual pnl/date data)

tech_stack:
  added: []
  patterns:
    - Optional int param with None default for backward compat
    - Private helper _parse_pnl_response isolating BRAIN schema variations

key_files:
  modified:
    - db.py
    - ideator.py
    - hunt.py
    - selfcorr.py
    - test_phase4.py

decisions:
  - delay-aware dedup is opt-in via delay= kwarg; all existing callers unchanged
  - _parse_pnl_response handles 3 BRAIN schema shapes + fallback; returns [],[] on exception
  - mutation path in hunt.py left unchanged (uses _is_passable, not generate_candidates)

metrics:
  duration: ~300s
  completed_date: "2026-06-13"
---

# Quick Task 260613-kpu Summary

**One-liner:** Fixed delay-blind novelty dedup (db.expr_exists + ideator + hunt) and selfcorr PnL parser (schema+records → {pnls, dates}) to unblock delay-0 hunt runs.

## What Was Done

### Task 1: Delay-aware novelty dedup (db.py, ideator.py, hunt.py)

**Bug:** `db.expr_exists` matched on expression text only. A delay-0 run generated the same expressions already stored for delay-1, so every candidate was dropped as a duplicate before any simulation ran — resulting in 0 candidates.

**Fix:**
- `db.expr_exists(conn, expression, delay=None)` — new optional `delay` int param. When `delay` is provided, query uses `WHERE expression=? AND delay=?`. When `None` (default), uses `WHERE expression=?` (original behavior, fully backward-compatible).
- `ideator.generate_candidates(..., delay=None)` — new `delay` kwarg threaded into the `db.expr_exists` call at the dedup point.
- `hunt.py` Gen 0 path updated: `ideator.generate_candidates(conn, thesis, delay=delay)` — passes the already-in-scope `delay` variable.
- Mutation path (`_is_passable`) and all callers in `editor.py`, `grade.py`, `find_alphas.py` left unchanged — they continue to use expression-only dedup.

**Verification:** Task 1 inline checks: PASS

### Task 2: selfcorr PnL parser for schema+records format (selfcorr.py)

**Bug:** `fetch_and_cache_pnl` called `pnl_data.get("pnls", [])` / `pnl_data.get("dates", [])` but BRAIN returns `{schema, records}`. Every cached PnL file was written empty, breaking local self-correlation computation.

**Fix:** Added `_parse_pnl_response(pnl_data)` private helper that:
1. Extracts column name list from `schema` (handles list, `schema["name"]`, `schema["properties"]`, or fallback to index 0/1).
2. Finds `"date"` and `"pnl"` columns case-insensitively.
3. Reads `pnl_data.get("records", [])` and extracts per-column lists.
4. Returns `(dates, pnls)`. Returns `([], [])` on any exception (D-13 graceful degrade).

`fetch_and_cache_pnl` now calls `dates, pnls = _parse_pnl_response(pnl_data)`. On-disk cache format `{"pnls": ..., "dates": ...}` and `load_returns` are unchanged.

**Verification:** Task 2 inline checks: PASS

### Task 3: Regression tests (test_phase4.py)

Added three tests after existing test functions:

- `test_expr_exists_delay_aware` — verifies delay=0 does not match delay=1 row; delay=1 matches; no-delay matches (backward compat).
- `test_queueable_delay0_passes_when_only_delay1_exists` — verifies full chain: dedup_alpha_id=None for delay-0 candidate when only delay-1 row exists; candidate passes `ideator.queueable`.
- `test_fetch_and_cache_pnl_schema_records` — uses MagicMock client returning schema+records fixture; verifies cached file has 3 non-empty pnls/dates.

## Verification Results

```
Task 1 inline checks: PASS
Task 2 inline checks: PASS

3 new tests: 3 passed in 0.07s
Full suite:  20 passed, 14 warnings in 0.07s
imports OK
```

## Deviations from Plan

None - plan executed exactly as written.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. All changes are pure logic fixes within existing function boundaries.

## Self-Check: PASSED

- db.py: delay-aware expr_exists present
- ideator.py: delay kwarg in generate_candidates, threaded to db.expr_exists
- hunt.py: delay= passed to generate_candidates in Gen 0 path
- selfcorr.py: _parse_pnl_response helper present, fetch_and_cache_pnl uses it
- test_phase4.py: 3 new tests added, all pass
- Full suite: 20 passed, 0 failures
- Import smoke: PASS
