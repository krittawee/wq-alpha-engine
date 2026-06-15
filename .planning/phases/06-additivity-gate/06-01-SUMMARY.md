---
phase: 06-additivity-gate
plan: "01"
subsystem: selfcorr
tags: [selfcorr, pnl-cache, book-reference, backfill, bug-fix, additivity]
dependency_graph:
  requires: []
  provides:
    - selfcorr.get_book_pnl_paths
    - selfcorr._null_stale_pnl_paths
    - selfcorr.backfill_active_pnl (D-04 fix)
  affects:
    - additivity.py (Plan 2 will import get_book_pnl_paths)
    - selfcorr.backfill_active_pnl call sites (hunt.py, manual backfill)
tech_stack:
  added: []
  patterns:
    - stdlib Path.exists() probe for cache-staleness check
    - executemany batch UPDATE for bulk NULL reset
key_files:
  created: []
  modified:
    - selfcorr.py
    - test_phase4.py
decisions:
  - "D-03: Book = ACTIVE-status alphas only (get_book_pnl_paths), never 'pass' or 'UNSUBMITTED'"
  - "D-04: Stale pnl_path nulled before backfill SELECT so missing-file rows are re-fetched (_null_stale_pnl_paths)"
metrics:
  duration: "~8 minutes"
  completed: "2026-06-15"
  tasks: 2
  files: 2
---

# Phase 06 Plan 01: selfcorr Book-Reference Primitives Summary

**One-liner:** Added `get_book_pnl_paths` (ACTIVE-only PnL paths for additivity gate) and `_null_stale_pnl_paths` (stale-cache null fix), wired into `backfill_active_pnl` to fix the D-04 no-op bug.

## What Was Built

### Task 1 — selfcorr.py additions

Three changes to `/Users/winter.__.kor/quant/selfcorr.py`:

1. **`get_book_pnl_paths(conn)`** (lines 307-325): New public function placed immediately after `get_reference_pnl_paths`. Queries `status='ACTIVE' AND pnl_path IS NOT NULL`. Returns `list[str]`. Used by the additivity module (Plan 2) to build the reference book for competition-score-aligned correlation. Intentionally does NOT include `'pass'` rows — those are for dedup only, not the competition book.

2. **`_null_stale_pnl_paths(conn)`** (lines 436-462): Private helper placed immediately before `backfill_active_pnl`. Queries ALL rows with `pnl_path IS NOT NULL`, probes each with `Path(pnl_path).exists()`, batch-updates stale rows to `NULL` via `executemany`, commits, returns count nulled.

3. **`backfill_active_pnl` fix** (line 486): Added `n_stale = _null_stale_pnl_paths(conn)` as the very first statement in the function body, before the `SELECT ... WHERE status='ACTIVE' AND pnl_path IS NULL` query. When `n_stale > 0`, prints a diagnostic message. This fixes the D-04 bug: previously, all 16 ACTIVE alphas had `pnl_path` set in DB (from a prior backfill run) but the `pnl_cache/` directory was cleared on disk — so the SELECT found 0 rows and every subsequent proxy correlation saw an empty reference set.

### Task 2 — test_phase4.py (4 new tests)

All tests use `db.init_db(':memory:')`, zero BRAIN API calls, pass in 0.14s:

| Test | What it verifies |
|------|------------------|
| `test_phase6_plan1_get_book_pnl_paths_active_only` | ACTIVE path returned; 'pass' and 'UNSUBMITTED' excluded |
| `test_phase6_plan1_get_book_pnl_paths_none_when_empty` | Empty DB → `[]` |
| `test_phase6_plan1_null_stale_pnl_paths` | 2 stale rows → count=2, both columns NULL |
| `test_phase6_plan1_backfill_nulls_stale_before_fetch` | Full D-04 fix: stale path cleared → SELECT finds row → `get_pnl` called once → `pnl_path` re-set |

## Verification Results

```
./venv/bin/python -m pytest test_phase4.py -k "phase6_plan1" --tb=short -x -q
4 passed, 33 deselected in 0.06s

./venv/bin/python -m pytest test_phase4.py --tb=short -q
37 passed, 18 warnings in 0.11s   # zero regressions
```

`get_reference_pnl_paths` is unchanged — still includes `'pass'` rows for `proxy_gate` dedup.

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new network endpoints, auth paths, or trust boundaries introduced. `_null_stale_pnl_paths` performs only local `Path.exists()` probes and a `NULL`-only UPDATE — consistent with T-06-01 (mitigate) disposition in the plan's threat register.

## Commits

| Task | Commit | Message |
|------|--------|---------|
| Task 1 | `77556f7` | `feat(06-01): add get_book_pnl_paths, _null_stale_pnl_paths, fix backfill` |
| Task 2 | `7c18160` | `test(06-01): add 4 offline tests for book-reference primitives (phase6_plan1)` |

## Self-Check: PASSED

- `selfcorr.py` modified: confirmed present
- `test_phase4.py` modified: confirmed present
- Commit `77556f7` exists: yes
- Commit `7c18160` exists: yes
- 4 `phase6_plan1` tests pass: yes (4 passed, 33 deselected)
- `get_reference_pnl_paths` unchanged: confirmed (`IN ('pass', 'ACTIVE')` intact)
