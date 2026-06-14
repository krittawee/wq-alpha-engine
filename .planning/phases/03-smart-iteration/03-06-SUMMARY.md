---
phase: 03-smart-iteration
plan: "06"
subsystem: test-acceptance
tags:
  - testing
  - phase3
  - acceptance-gate
  - fsa
  - selfcorr
  - editor
dependency_graph:
  requires:
    - 03-01 (editor.py — classify_from_checks, diagnose_and_mutate)
    - 03-02 (selfcorr.py — max_pearson, load_returns, get_selfcorr_limit)
    - 03-03 (fsa.py — mine_frequent_motifs, filter_candidates, diversity_metric)
    - 03-04 (db.py — diagnosis column, upsert_alpha, init_db)
  provides:
    - Machine-verifiable acceptance gate for all 4 Phase 3 ROADMAP success criteria
  affects:
    - Phase 3 completion signaling
tech_stack:
  added: []
  patterns:
    - TempDir fixture pattern (temp DB copy, no live DB mutation)
    - unittest.mock.patch for LLM subprocess isolation
    - Direct DB insert + module function call pattern (zero BRAIN API)
key_files:
  created: []
  modified:
    - test_phase3.py
decisions:
  - Expanded test_phase3.py from 8 tests (criterion 1 only) to 11 tests covering all 4 criteria
  - Used unittest.mock.patch("editor._call_llm_editor") to isolate LLM calls in criterion 1 (diagnosis persistence) and criterion 2 (mutation lineage) — no subprocess spawned
  - Criterion 2 mutation lineage test inserts known valid operator (ts_mean) and field (close) into temp DB catalog so validate.validate can accept the mutation expression
  - Case C (20% boundary) documented as NEAR (gap=0.20 satisfies gap<=0.20) — at-boundary behavior confirmed
  - Case E (EPSILON floor) tests that ZeroDivisionError is not raised for value=0.0/limit=0.0 — the actual classification result (near) is a secondary assertion
  - Criterion 4 diversity_metric test uses cold-start with 4 alphas then adds 2 more to trigger motif mining, then adds 4 more with different motif to show before/after diversity change
metrics:
  duration: "~8 minutes"
  completed: "2026-06-10"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 1
---

# Phase 3 Plan 06: test_phase3.py — All 4 Criterion Tests Summary

**One-liner:** Extended test_phase3.py with 11 tests covering all 4 ROADMAP Phase 3 success criteria using synthetic DB fixtures and mock patches — zero BRAIN API calls.

## What Was Built

Extended the existing `test_phase3.py` (which had 8 tests covering criterion 1 only) to include all 4 ROADMAP Phase 3 success criteria:

### Criterion 1: Editor Classification + Diagnosis Persistence

The existing 5 classification tests were retained. The main `test_criterion_1_near_classification` function was expanded to cover all 6 cases (A-F) in a single test:
- **Case A:** NEAR (LOW_SHARPE value=1.22, limit=1.25, gap=2.4%)
- **Case B:** Hard FAIL (MATCHES_COMPETITION)
- **Case C:** NEAR at exactly 20% boundary (value=1.0, limit=1.25, gap=0.20)
- **Case D:** PASS (all-PENDING — Pitfall 2)
- **Case E:** EPSILON floor guard (LOW_SUB_UNIVERSE_SHARPE 0.0/0.0 — no ZeroDivisionError)
- **Case F:** FAIL due to D-07 cap (3 numeric fails, each within 20%)

**WARNING 2 / ROADMAP criterion 1 persistence:** Added diagnosis persistence check that mocks `editor._call_llm_editor` to return a fixed diagnosis for Case A (NEAR alpha) and verifies that `alphas.diagnosis` IS NOT NULL and equals the returned string after `diagnose_and_mutate`.

### Criterion 2: Mutation Lineage (parent_alpha_id at insert time)

`test_criterion_2_mutation_lineage` — new test that:
1. Inserts a NEAR alpha with LOW_SHARPE fail
2. Seeds the temp DB catalog with known valid operator (`ts_mean`) and field (`close`)
3. Mocks `_call_llm_editor` to return one valid expression (`ts_mean(close,10)`) + one invalid (`UNKNOWN_OP`)
4. Calls `diagnose_and_mutate` and verifies:
   - Valid mutation appears in result; invalid mutation dropped by validate gate
   - DB query confirms stub row with `parent_alpha_id='TEST_MUT_SRC'` and `status='queued'`
   - `parent_alpha_id` column exists in schema

### Criterion 3: Local PnL Self-Corr Pre-filter

`test_criterion_3_pearson_prefilter` — new test that:
1. Builds synthetic PnL JSON files (100 days): identical series, orthogonal series
2. Verifies `max_pearson(identical, [identical]) > 0.99`
3. Verifies `max_pearson(orthogonal, [identical]) < 0.5`
4. Verifies `load_returns` returns daily differences (len = pnls-1, all floats ~0.01)
5. Verifies `get_selfcorr_limit` returns None with no DB row, then 0.7 after inserting a SELF_CORRELATION check — confirms not hardcoded

### Criterion 4: FSA Mining + Diversity Metric

`test_criterion_4_fsa_mining` — new test that:
1. Inserts 4 PASS alphas → `mine_frequent_motifs` returns `[]` (cold-start guard)
2. Adds 2 more PASS alphas → 6 total → `ts_rank(FIELD,NUM)` mined (appears in 6/6)
3. `filter_candidates` drops `ts_rank(close,5)`, keeps `rank(close)`
4. **Before/after diversity_metric:** 6 ts_rank alphas → high top_motif_share; add 4 `rank(close)` alphas → lower top_motif_share; asserts `before > after`
5. Empty DB → `diversity_metric` returns `pass_alpha_count=0`

## Test Results

```
11 passed in 0.17s
```

All 11 tests pass. Zero grade/simulate/login calls (only comment in docstring).

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | test_phase3.py — all 4 criterion tests | c0745c2 | test_phase3.py |

## Deviations from Plan

None — plan executed exactly as written. The existing 8 tests were preserved and extended. The consolidated `test_criterion_1_near_classification` function covers all Cases A-F within a single test function (as specified), while the supplementary individual test functions from the prior wave remain for regression coverage.

## Self-Check: PASSED

- FOUND: test_phase3.py
- FOUND: 03-06-SUMMARY.md
- FOUND: commit c0745c2 (test_phase3.py — all 4 criterion tests)
