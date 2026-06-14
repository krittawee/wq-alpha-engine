---
phase: 04-optimization-polish
plan: "04"
subsystem: decay-monitor
tags: [decay, monitoring, checks-history, time-series, sqlite]
dependency_graph:
  requires: [04-01, 04-02]
  provides: [decay_monitor.detect_decay, decay_monitor.run_decay, decay.py-CLI]
  affects: [grade.py, db.checks_history]
tech_stack:
  added: []
  patterns: [single-shot-auth, append-only-history, parameterized-SQL, client-session-get]
key_files:
  created:
    - decay_monitor.py
    - decay.py
  modified: []
decisions:
  - "detect_decay returns no_data only when total checks_history rows < 2 for the alpha; individual metric rows < 2 are skipped (not a global no_data)"
  - "run_decay scoped to status IN ('pass','ACTIVE') — excludes 363 UNSUBMITTED pre-Phase-2 alphas per Open Question 3 resolution"
  - "GET /alphas/{id} uses client._session.get (authenticated session) not bare requests.get — mirrors grade.py line 446 pattern"
metrics:
  duration: "163s"
  completed: "2026-06-11T05:34:51Z"
  tasks_completed: 2
  files_created: 2
---

# Phase 4 Plan 04: Decay Monitor Summary

**One-liner:** Deterministic decay detection via checks_history time-series with parameterized SQL queries, 15% configurable threshold, single-shot BRAIN auth, and 401-safe partial-run semantics.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | detect_decay + DEFAULT_DECAY_THRESHOLD | b8a5721 | decay_monitor.py (new) |
| 2 | run_decay orchestrator + decay.py CLI | 85626e3 | decay_monitor.py (extended), decay.py (new) |

## What Was Built

### decay_monitor.py

- `DEFAULT_DECAY_THRESHOLD = 0.15` at module top
- `detect_decay(conn, alpha_id, threshold_pct)` — compares last 2 checks_history rows per metric:
  - Returns `no_data` when total alpha history rows < 2
  - Returns `degraded` + metric details when `(old-new)/abs(old) > threshold_pct`
  - Returns `stable` when no metric exceeds threshold
  - Skips None values and abs(old_val)<1e-6 (no division by zero)
  - All SQL uses `?` parameterized queries (T-04-14 mitigated)
- `run_decay(client, db_path, threshold_pct)` — re-checks PASS+ACTIVE alphas:
  - Queries `WHERE status IN ('pass', 'ACTIVE')` (not UNSUBMITTED)
  - `client._session.get(f"{BASE_URL}/alphas/{alpha_id}")` for IS stats
  - Reads `limit_val` from `checks` table (never hardcodes per CLAUDE.md)
  - Calls `grade.trigger_correlation_check` + `grade.poll_correlation`
  - Calls `db.append_checks_history` per alpha before `detect_decay`
  - 401 propagates immediately, stops run; partial rows preserved
  - TimeoutError from poll: warning logged, loop continues
  - Calls `obsidian.write_decay_note` if module available (D-07)
  - Prints CLI table of degraded alphas

### decay.py

- argparse with `--db` and `--threshold` (default 0.15 = 15%)
- Single-shot `login()` call (CLAUDE.md: never re-auth in-loop)
- 401 HTTPError caught at top-level -> print message + `sys.exit(1)`

## Test Results

All 4 OPT-02 tests pass:
- `test_decay_no_data` — PASSED
- `test_decay_degraded` — PASSED
- `test_decay_stable` — PASSED
- `test_history_append_only` — PASSED

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed no_data semantics for single-metric history**
- **Found during:** Task 1 -- test_decay_stable failed with status='no_data'
- **Issue:** RESEARCH.md Pattern 4 shows `return no_data` immediately when any metric has <2 rows. But `test_decay_stable` inserts 2 rows for LOW_SHARPE only (0 for LOW_FITNESS) and expects 'stable'. The spec's code would return `no_data` when iterating to LOW_FITNESS.
- **Fix:** Changed semantics so `no_data` is returned only when `total_rows < 2` for the entire alpha (quick early-exit check), and individual metrics with <2 rows are `continue`'d (not a global no_data). An `any_evaluated` flag tracks if any metric was assessed; returns `no_data` at end only if none were evaluable.
- **Files modified:** decay_monitor.py
- **Commit:** b8a5721

## Known Stubs

None. `detect_decay` and `run_decay` are fully wired. `decay.py` is a real CLI entrypoint. The `obsidian.write_decay_note` call is guarded by a try/except ImportError (obsidian module delivered by Plan 05).

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced beyond the plan's defined scope. `run_decay` uses `client._session.get` (authenticated session) for all BRAIN API calls -- no new trust boundaries. All SQL parameterized. No new packages installed (T-04-SC: accept).

## Self-Check: PASSED

- [x] decay_monitor.py exists at worktree root
- [x] decay.py exists at worktree root
- [x] Commit b8a5721 exists (feat(04-04): detect_decay)
- [x] Commit 85626e3 exists (feat(04-04): run_decay + decay.py CLI)
- [x] All 4 OPT-02 tests pass
