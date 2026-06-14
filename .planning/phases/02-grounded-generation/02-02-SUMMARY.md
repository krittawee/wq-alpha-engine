---
phase: 02-grounded-generation
plan: "02"
subsystem: ideator
tags: [ideator, candidate-generation, archetype, validate, dedup, seeds, tdd]
dependency_graph:
  requires: [researcher.py, validate.py, db.py, alpha_kb.db]
  provides: [ideator.py]
  affects: [02-03-find-alphas, 02-04-checkpoint]
tech_stack:
  added: []
  patterns: [tdd, grounded-skeletons, validate-gate, expr-exists-dedup, seeds-txt-emit]
key_files:
  created:
    - ideator.py
    - test_ideator_candidates.py
    - test_ideator_gates.py
  modified: []
decisions:
  - "winsorize() uses positional numeric arg (not std= keyword) — validator parses 'std' as unknown data-field token"
  - "nws12_afterhsz_sl VECTOR-type field always wrapped in vec_avg via module-level _VECTOR_FIELDS frozenset"
  - "validate + dedup gates integrated in Task 1 implementation (generate_candidates returns fully-gated candidates)"
  - "8 per-archetype variant functions dispatch via _VARIANT_FNS table; fallback window-perturbation guarantees >=4 candidates"
metrics:
  duration: "~5 minutes"
  completed: "2026-06-08"
  tasks_completed: 2
  files_changed: 3
---

# Phase 02 Plan 02: ideator.py — Candidate Generation + Validate Gate + Dedup — Summary

**One-liner:** Archetype-skeleton ideator composing 4-8 catalog-grounded FastExpr candidates per thesis, gated by validate.validate (zero unknown-token rejections) and db.expr_exists dedup, with cli.py-compatible seeds.txt serialization.

## What Was Built

`ideator.py` (462 lines) exports 3 public functions:

- `generate_candidates(conn, thesis, n=None)` — consumes a thesis dict from `researcher.build_thesis` and produces 4-8 candidate records. Uses a per-archetype variant-generation function (dispatch via `_VARIANT_FNS` table) to compose grounded FastExpr strings from the 8 LOCKED skeleton expressions plus window/field/normalizer variations drawn from `thesis.source_operators` and `thesis.source_datafields`. Every candidate is gated through `validate.validate(conn, expr)` (criterion 2) and `db.expr_exists(conn, expr)` (criterion 3). Returns list of dicts: `{expression, archetype, valid, validation_reason, dedup_alpha_id}`.

- `queueable(candidates)` — filters to valid==True AND dedup_alpha_id==None subset (criteria 2 + 3 combined).

- `to_seeds_text(candidates, header=None)` — serializes queueable candidates to exact seeds.txt format matching cli.py:62-64 parse contract: one FastExpr per body line, leading `#`-comment header, blank body lines omitted.

40 tests across 2 test files cover all acceptance criteria. All pass.

## Verification Results

```
OK reversal 8        # Task 1 verify: 8 candidates, archetype inherited
OK queueable 8       # Task 2 verify: 8 queueable, 0 validate failures, cli-parseable

40 passed            # All tests pass

# Per-archetype queueable counts:
reversal:          8 queueable, 0 validate failures
momentum:          5 queueable, 0 validate failures
value_garp:        5 queueable, 0 validate failures
quality:           5 queueable, 0 validate failures
growth:            6 queueable, 0 validate failures
low_volatility:    6 queueable, 0 validate failures
liquidity_volume:  6 queueable, 0 validate failures
sentiment_event:   8 queueable, 0 validate failures

grep gate: 0 grade/simulate/login references  # T-02-06 satisfied
ideator.py: 462 lines (> 90 minimum)
```

## Decisions Made

1. **winsorize positional arg:** The grounding brief skeleton uses `winsorize(signal, std=4)`. The validator parses `std` as an identifier not in `_EXCLUSIONS` → treats it as a data-field token → fails with "unknown data field: std". Fixed by using positional form `winsorize(signal, 4)` — numeric literals are never flagged by the validator.

2. **VECTOR field wrapping:** `nws12_afterhsz_sl` has type=VECTOR in the catalog. The module-level `_VECTOR_FIELDS = frozenset({"nws12_afterhsz_sl"})` and `_wrap_vector()` helper ensure any VECTOR field is wrapped in `vec_avg()` per steering notes. All 8155 seed fields checked; only this one is VECTOR-typed.

3. **Gates integrated in generate_candidates:** Both `validate.validate` and `db.expr_exists` calls are part of the core `generate_candidates` function rather than a separate "Task 2 extension" — this kept the public API surface minimal and the behavior correct from Task 1 onward.

4. **Fallback window perturbation:** If a variant function produces fewer than 4 candidates (edge case for archetypes with sparse source_fields), `generate_candidates` perturbates the skeleton with numeric window substitutions to guarantee the D-01 floor.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed winsorize skeleton for value_garp**
- **Found during:** Task 1 — running `validate.validate` against skeleton expressions revealed `std` being parsed as unknown field token
- **Issue:** `winsorize(rank(divide(bookvalue_ps, close)), std=4)` fails validate with "unknown data field: std"
- **Fix:** Changed to positional `winsorize(rank(divide(bookvalue_ps, close)), 4)` — numeric literals are never flagged
- **Files modified:** ideator.py (skeleton map + value_garp variant function)

### TDD Gate Note

Task 2 (gate/dedup/seeds.txt tests): Both `validate.validate` and `db.expr_exists` were already integrated in the Task 1 implementation since the behavior was naturally unified in `generate_candidates`. Task 2 tests validated correctness guarantees rather than discovering absent behavior. 40/40 tests pass. This mirrors the pattern from Wave 1 (02-01 Task 2).

## Known Stubs

None. All archetype variant functions produce real FastExpr expressions using catalog-verified tokens. No placeholder text or hardcoded empty values.

## Threat Flags

None. No new network endpoints, auth paths, or BRAIN API calls introduced. `ideator.py` reads only from `sqlite3.Connection` (passed in) and the module-level skeleton table.

## Self-Check: PASSED

- ideator.py exists: FOUND (462 lines)
- test_ideator_candidates.py exists: FOUND (15 tests)
- test_ideator_gates.py exists: FOUND (25 tests)
- Commits:
  - 54d0ec5 (test RED Task 1)
  - 514017d (feat GREEN Task 1 + Task 2 gates)
  - 71c5a43 (test Task 2 gate/dedup/seeds tests)
- 40/40 tests pass
- Plan verify commands: both print OK
- grep gate: 0 grade/simulate/login references
- All must_have artifacts satisfied (def generate_candidates, def to_seeds_text, def queueable, validate.validate pattern, db.expr_exists pattern, 462 > 90 lines)
