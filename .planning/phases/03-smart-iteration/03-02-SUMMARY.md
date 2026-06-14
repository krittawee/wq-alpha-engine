---
phase: 03-smart-iteration
plan: "02"
subsystem: selfcorr
tags: [pnl-filter, self-correlation, pearson, tdd, stdlib]
dependency_graph:
  requires: [db.py, brain_client.py (get_pnl)]
  provides: [selfcorr.py]
  affects: [grade.py (plan 04), hunt.py (plan 05)]
tech_stack:
  added: []
  patterns: [tdd-red-green, graceful-degrade, 401-propagation, parameterized-sql]
key_files:
  created:
    - selfcorr.py
    - test_selfcorr.py
  modified: []
decisions:
  - "60-day minimum overlap threshold for _date_overlap_returns (per Q1 open question in RESEARCH.md)"
  - "test_no_hardcoded_0_7 checks for 'return 0.7' pattern rather than any mention of '0.7' (docstrings legitimately reference the limit value)"
  - "test_above/below_limit_is_duplicate use 70 dates to exceed 60-day overlap threshold"
metrics:
  duration: "~15 minutes"
  completed: "2026-06-10"
  tasks_completed: 2
  files_count: 2
---

# Phase 3 Plan 02: selfcorr.py Local PnL Self-Correlation Pre-Filter Summary

**One-liner:** Stdlib-only Pearson pre-filter with two-stage gate (D-08a proxy + D-08b precise), 401 propagation, and runtime DB-read of self-corr limit — never hardcodes 0.7.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | TDD failing tests for PnL fetch, caching, returns | 52499ec | test_selfcorr.py |
| 2 (GREEN) | selfcorr.py implementation + test fixes | 1054751 | selfcorr.py, test_selfcorr.py |

## What Was Built

`selfcorr.py` — importable module providing local PnL-based self-correlation filtering for
the grading pipeline (grade.py plan 04) and hunt loop (hunt.py plan 05).

### Public API (8 functions)

- `fetch_and_cache_pnl(client, alpha_id, conn, pnl_dir)` — downloads via `client.get_pnl()`, caches JSON to `pnl_cache/{alpha_id}.json`, updates `alphas.pnl_path`; 401 re-raised, all other errors return None
- `load_returns(pnl_path)` — reads cached JSON, filters to last 2 years, converts cumulative PnL to daily returns; returns `[]` on any error
- `get_reference_pnl_paths(conn)` — SELECT pnl_path WHERE status IN ('pass', 'ACTIVE')
- `get_selfcorr_limit(conn)` — reads SELF_CORRELATION limit_val from checks table; returns None if unavailable; no hardcoded 0.7
- `max_pearson(candidate_path, reference_paths)` — max Pearson across reference set with date-overlap alignment; skips references with <60-day overlap
- `is_duplicate_by_pnl(candidate_path, reference_paths, limit_val, margin)` — D-08b precise post-sim gate
- `proxy_gate(parent_alpha_id, conn)` — D-08a pre-sim proxy gate; returns False (allow) on any degradation path
- `backfill_active_pnl(client, conn, db_path, pnl_dir)` — sequential PnL fetch for ACTIVE alphas with NULL pnl_path; warns when zero reference PnLs remain after run

### Private helpers

- `_filter_to_recent(pnls, dates, years=2)` — filters to most recent N years by date
- `_pnls_to_daily_returns(pnls)` — forward-fills None/NaN, then computes forward-differences
- `_pearson(x, y)` — stdlib math Pearson, min-len alignment, zero-stddev guard → 0.0
- `_date_overlap_returns(path_a, path_b)` — loads two PnL JSONs, aligns to date overlap, returns `([], [])` if overlap < 60 trading days

## Test Coverage

25 tests in `test_selfcorr.py` covering:
- 401 propagation and graceful degrade (500, exceptions)
- fetch_and_cache_pnl file creation and DB update
- load_returns: daily diffs count, 2-year truncation
- _pearson: perfect correlation, insufficient data, empty, constant series
- All 8 public functions present
- No hardcoded 0.7 in get_selfcorr_limit
- Warning present in backfill_active_pnl source
- get_selfcorr_limit DB read and None-when-empty
- get_reference_pnl_paths filters correctly
- proxy_gate returns False on all degradation paths
- is_duplicate_by_pnl above/below threshold (using 70-date vectors for >60 overlap)
- backfill_active_pnl: 401 propagates, non-401 skipped, warning printed, count returned

All 25 tests pass.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_no_hardcoded_0_7 false positive on docstring mention**
- **Found during:** GREEN phase test run
- **Issue:** Test checked for any occurrence of "0.7" in `get_selfcorr_limit` source, but the docstring legitimately says "NEVER hardcode 0.7" — causing a false failure
- **Fix:** Changed test to use `re.search(r'\breturn\s+0\.7\b', fn_src)` to catch only actual `return 0.7` statements, plus runtime check (None from empty DB confirms function reads DB)
- **Files modified:** test_selfcorr.py
- **Commit:** 1054751

**2. [Rule 1 - Bug] test_above_limit_is_duplicate failed with 50-date vectors**
- **Found during:** GREEN phase test run
- **Issue:** `_date_overlap_returns` requires >= 60 trading days of overlap; test used 50 dates → returned `([], [])` → max_pearson returned 0.0 → is_duplicate returned False
- **Fix:** Updated both `test_above_limit_is_duplicate` and `test_below_limit_not_duplicate` to use 70-date vectors (> 60 threshold)
- **Files modified:** test_selfcorr.py
- **Commit:** 1054751

## Threat Model Coverage

| Threat | Status |
|--------|--------|
| T-03-04: 401 propagation (auth expiry) | Mitigated — 401 re-raised in fetch_and_cache_pnl |
| T-03-06: backfill inside sim pool | Mitigated — docstring + module comment explicitly say: call sequentially before sim pool |
| T-03-07: hardcoded self-corr cutoff | Mitigated — get_selfcorr_limit reads from DB; test asserts no `return 0.7` pattern |
| T-03-05: pnl_cache files on disk | Accepted — local single-user tool, non-sensitive financial time series |
| T-03-SC: no new pip installs | Confirmed — stdlib only (json, math, sqlite3, pathlib, datetime); requests already present |

## Known Stubs

None. All functions are fully implemented.

## Threat Flags

None. No new network endpoints or auth paths introduced. pnl_cache/ files are read-only local storage from BRAIN API responses already handled by existing auth model.

## Self-Check: PASSED

- selfcorr.py: FOUND at worktree root
- test_selfcorr.py: FOUND at worktree root
- RED commit 52499ec: confirmed in git log
- GREEN commit 1054751: confirmed in git log
- All 25 tests pass: confirmed via pytest run
