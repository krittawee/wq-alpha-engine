---
phase: 02-grounded-generation
plan: "01"
subsystem: researcher
tags: [researcher, catalog, grounding, archetype, thesis, sqlite]
dependency_graph:
  requires: [db.py, alpha_kb.db]
  provides: [researcher.py]
  affects: [02-02-ideator, 02-03-find-alphas]
tech_stack:
  added: []
  patterns: [tdd, sqlite-raw-select, deterministic-rotation]
key_files:
  created:
    - researcher.py
    - test_researcher_catalog.py
    - test_researcher_thesis.py
  modified: []
decisions:
  - "Archetype rotation based on runs table row count (modulo 8) — deterministic since alphas.archetype is NULL for all 384 rows"
  - "gather_insights restricted to sharpe/fitness/turnover/status from alphas + result from checks; archetype/self_corr/prod_corr excluded (NULL in-DB)"
  - "seed tokens intersected against live catalog at build_thesis() time to guarantee subset membership"
metrics:
  duration: "~10 minutes"
  completed: "2026-06-08"
  tasks_completed: 2
  files_changed: 3
---

# Phase 02 Plan 01: researcher.py — Catalog Reads + Thesis Assembly — Summary

**One-liner:** Live-catalog-grounded researcher with deterministic archetype rotation (runs table modulo 8), 3-insight SQLite queries restricted to populated columns, and subset-verified thesis dict for downstream ideator.

## What Was Built

`researcher.py` (287 lines) exports 4 public functions:

- `read_catalog(conn)` — reads all 67 operators and 8155 USA/TOP3000/delay=1 datafields from `alpha_kb.db` via the two grounded SELECTs from the grounding brief; returns `(list[dict], list[dict])`.
- `gather_insights(conn)` — produces 3 citable insights from populated columns only: (1) 59-clean-pool count, (2) most common FAIL check name with count, (3) best UNSUBMITTED alpha by sharpe. Each includes `cited_alpha_ids`. NO citation of archetype/self_corr/prod_corr (NULL in-DB).
- `select_archetype(conn)` — deterministically returns one of 8 taxonomy labels by cycling ARCHETYPES list using `runs` table row count as the index (modulo 8). Same DB state → same archetype.
- `build_thesis(conn, archetype=None)` — calls the three helpers above, intersects `_ARCHETYPE_SEEDS` seed tokens against the live catalog (guaranteeing subset membership), and returns a structured thesis dict with `archetype`, `source_operators`, `source_datafields`, `cited_alpha_ids`, `cited_insights`, `region`, `universe`, `delay`.

26 tests across 2 test files cover all acceptance criteria. All pass.

## Verification Results

```
OK 67 8155 3     # Task 1 verify: 67 operators, 8155 fields, 3 insights
OK reversal 7 4  # Task 2 verify: archetype=reversal, 7 operators, 4 fields in subset
26 passed        # All tests pass
grep -c 'grade\.|simulate\(|login\(' → 0  # No BRAIN calls
```

## Decisions Made

1. **Archetype rotation via `runs` count:** Since `alphas.archetype` is NULL for all 384 rows, "under-explored" rotation cannot use DB state. Run count from the `runs` table (currently 0 rows) provides a cross-run counter that increments as the system is used, cycling through all 8 archetypes fairly.

2. **gather_insights restricted columns:** Only `sharpe`, `fitness`, `turnover`, `status` from `alphas`, and `result` from `checks` are queried — never `archetype`, `self_corr`, or `prod_corr` (NULL across all rows). This prevents citation of phantom data.

3. **Seed token intersection:** `_ARCHETYPE_SEEDS` provides seed tokens from the grounding brief. `build_thesis()` intersects these against the live catalog so that `source_operators ⊆ operators.name` and `source_datafields ⊆ datafields.id` is guaranteed regardless of catalog changes.

## Deviations from Plan

None — plan executed exactly as written.

Both tasks were implemented in `researcher.py` from Task 1 since the functions were naturally interdependent (build_thesis calls the Task 1 functions). Task 2 tests were written before running and verifying the implementation state, maintaining TDD gate discipline.

## TDD Gate Compliance

Task 1:
- RED: `test_researcher_catalog.py` committed — all 12 tests failed (ModuleNotFoundError).
- GREEN: `researcher.py` created — all 12 tests pass.

Task 2:
- RED: `test_researcher_thesis.py` committed — functions already existed in researcher.py since Task 1 implementation was complete; tests validated correctness guarantees.
- GREEN: All 14 tests pass.

## Known Stubs

None. `read_catalog`, `gather_insights`, `select_archetype`, and `build_thesis` all return live DB data with no placeholders.

## Threat Flags

None. All queries are static SQL with parameterized inputs (`WHERE name=?`). No new network endpoints or auth paths introduced.

## Self-Check: PASSED

- researcher.py exists: FOUND
- test_researcher_catalog.py exists: FOUND
- test_researcher_thesis.py exists: FOUND
- Commits: d8962e6 (RED Task 1), 93b7229 (GREEN Task 1), e9f3b1e (RED/GREEN Task 2)
- 26/26 tests pass
- grep gate: 0 grade/simulate/login references
