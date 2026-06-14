---
phase: quick-260613-ldy
plan: 01
status: complete
subsystem: validate / ideator / grade / tests
tags: [bug-fix, winsorize, named-param, brain-error-surface, tdd]
completed_date: "2026-06-13"
duration_minutes: 5
tasks_completed: 3
tasks_total: 3
files_changed:
  modified: []
  already_applied:
    - validate.py
    - ideator.py
    - grade.py
    - test_phase4.py
key_decisions:
  - "winsorize uses std= named param per BRAIN catalog definition; validate.py excludes named-arg keys from data-field checks (REVERSES old workaround)"
  - "grade._simulate_to_alpha raises immediately with BRAIN's real error message when sim._result.status=ERROR; genuine throttle (no _result) still retries"
---

# Quick Task 260613-ldy: Fix winsorize named param std= in ideator

## One-liner

Fixed three interconnected bugs: validate.py now excludes named-arg keys (like `std=`) from data-field checks; ideator.py emits `winsorize(..., std=N)` everywhere; grade.py surfaces BRAIN's real error message instead of mislabeling ERROR as throttle.

## What Was Done

All three fixes were already applied to the working tree before execution began (pre-applied state). Execution confirmed correctness by running all verification steps.

### Task 1 — validate.py: exclude named-arg keys from bare_field_tokens

validate.py already contained the `named_arg_keys` extraction (lines 68-71) and the updated `bare_field_tokens` comprehension (lines 77-83) that exclude named-arg keys. The fix uses the pattern `\b([A-Za-z_]\w*)\s*=(?!=)` to identify word tokens immediately followed by `=` but not `==`.

test_phase4.py already contained `TestValidateNamedArgKeys` (4 tests). All 4 passed.

### Task 2 — ideator.py: emit winsorize with std= named param

All five emission sites in ideator.py already used `std=4`:
- `_SKELETONS["value_garp"]`: `winsorize(rank(divide(bookvalue_ps, close)), std=4)`
- `_make_value_garp_variants` subindustry variant: `std=4`
- `_make_value_garp_variants` EPS ratio variant: `std=4`
- `_make_quality_variants` winsorize wrapper: `std=4`
- Comment at line 30 updated to state `std=` named param

test_phase4.py already contained `TestIdeatorWinsorizeNamedParam` (3 tests). All 3 passed.

### Task 3 — grade.py: surface BRAIN sim ERROR instead of mislabeling as throttle

grade.py `_simulate_to_alpha` already contained the `_result` inspection block (lines 83-90) plus the `RuntimeError` re-raise guard (lines 96-99). The fix distinguishes `status=ERROR` (raise immediately with BRAIN's message) from the throttle/queue path (keep retrying).

test_phase4.py already contained `TestGradeSurfacesBrainError` (3 tests). All 3 passed.

## Verification Results

### Task 1 — TestValidateNamedArgKeys

```
test_phase4.py::TestValidateNamedArgKeys::test_dense_named_param_ts_decay_linear PASSED
test_phase4.py::TestValidateNamedArgKeys::test_genuine_unknown_field_still_fails PASSED
test_phase4.py::TestValidateNamedArgKeys::test_std_not_reported_as_unknown_field PASSED
test_phase4.py::TestValidateNamedArgKeys::test_winsorize_named_std_passes PASSED
4 passed in 0.01s
```

### Task 2 — TestIdeatorWinsorizeNamedParam

```
test_phase4.py::TestIdeatorWinsorizeNamedParam::test_quality_winsorize_uses_named_param PASSED
test_phase4.py::TestIdeatorWinsorizeNamedParam::test_value_garp_winsorize_uses_named_param PASSED
test_phase4.py::TestIdeatorWinsorizeNamedParam::test_winsorize_exprs_pass_validation PASSED
3 passed in 0.01s
```

### Task 3 — TestGradeSurfacesBrainError

```
test_phase4.py::TestGradeSurfacesBrainError::test_brain_error_does_not_retry PASSED
test_phase4.py::TestGradeSurfacesBrainError::test_brain_error_raises_with_real_message PASSED
test_phase4.py::TestGradeSurfacesBrainError::test_throttle_still_retries PASSED
3 passed in 0.08s
```

### Full Suite

```
30 passed, 14 warnings in 0.08s
```

### Import Smoke

```
imports OK
```

### End-to-End value_garp Offline Check

```
True group_neutralize(winsorize(rank(divide(bookvalue_ps, close)), std=4), industry)
True group_neutralize(winsorize(rank(divide(bookvalue_ps, close)), std=4), subindustry)
True group_neutralize(rank(divide(cashflow_op, cap)), industry)
True group_neutralize(winsorize(rank(divide(bookvalue_ps, close)), std=3), industry)
```

Every line starts with `True`. Every winsorize expression uses `std=`.

## Deviations from Plan

None. All three fixes were already applied to the working tree. Execution confirmed correctness via all verification steps without requiring any additional edits.

## State Note for Orchestrator

STATE.md contains a decision: "winsorize uses positional numeric arg — std= keyword causes 'std' to be parsed as unknown data-field token by validate.py". This plan REVERSES that workaround. Update STATE.md to replace that decision with: "winsorize uses std= named param per BRAIN catalog definition; validate.py excludes named-arg keys from data-field checks."

## Self-Check: PASSED

- validate.py exists with named_arg_keys fix: confirmed (lines 68-71)
- ideator.py exists with std= in all 4 winsorize emission sites: confirmed
- grade.py exists with _result inspection and immediate raise on ERROR: confirmed
- test_phase4.py exists with all 3 new test classes: confirmed
- Full pytest suite: 30 passed, 0 failures
- End-to-end value_garp check: all True, all winsorize use std=
