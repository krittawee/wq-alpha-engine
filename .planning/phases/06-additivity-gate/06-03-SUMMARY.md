---
phase: 06-additivity-gate
plan: "03"
subsystem: hunt
tags: [additivity, gate, hunt, integration-tests, best_submittable, ADD-03, ADD-04]
dependency_graph:
  requires:
    - additivity.rank_by_proxy
    - additivity.confirm_additive
    - additivity.CONFIRM_LIMIT
    - additivity.AdditivityResult
    - hunt._rank_best
  provides:
    - hunt._apply_additivity_gate
  affects:
    - hunt.best_submittable (gated at both assignment sites)
    - Phase 7 brute-force (will call same gate helper)
tech_stack:
  added: []
  patterns:
    - Two-layer gate helper extracted to private _apply_additivity_gate (ADD-03)
    - strict additive=True check — None and False both excluded (T-06-09)
    - Sequential confirm_additive calls never inside grade_many thread pool (T-06-10)
    - 401 propagates from confirm_additive through gate to CLI handler (no try/except in helper)
key_files:
  created: []
  modified:
    - hunt.py
    - test_phase4.py
decisions:
  - "ADD-03: _apply_additivity_gate enforced at both best_submittable assignment sites (line 313 and line 407 in updated hunt.py)"
  - "T-06-09: result.additive is True (strict) — None/inconclusive treated as non-additive"
  - "T-06-10: confirm_additive called sequentially in _apply_additivity_gate, never inside grade_many pool"
  - "Task 1 was committed before this wave (db398a6) — Task 2 adds the integration tests"
metrics:
  duration: "~5 minutes"
  completed: "2026-06-15"
  tasks: 2
  files: 1
---

# Phase 06 Plan 03: Hunt Additivity Gate Wiring Summary

**One-liner:** Wired `_apply_additivity_gate` into `hunt.py` at both `best_submittable` assignment sites — no alpha reaches submit-ready status on IS checks alone; two integration tests confirm gate blocks non-additives and passes confirmed-additive candidates.

## What Was Built

### Task 1 — hunt.py (committed as db398a6 before this wave)

`_apply_additivity_gate(client, all_pass_ids, conn)` private helper added to `hunt.py`:

1. Guard against empty `all_pass_ids` → return `None` immediately.
2. Build `pass_candidates` list from DB `pnl_path` lookups.
3. `ranked = additivity.rank_by_proxy(pass_candidates, conn)` — zero BRAIN calls, sorts ascending by `combined_corr`.
4. `proxy_survivors = [r for r in ranked if not r.proxy_drop]` — soft pre-filter.
5. Loop over `proxy_survivors[:additivity.CONFIRM_LIMIT]`: print log line, call `additivity.confirm_additive`. Only append to `confirmed_ids` when `result.additive is True` (strict — T-06-09).
6. If no confirmed IDs: print diagnostic, return `None`.
7. Return `_rank_best(confirmed_ids, conn)` — highest-Sharpe confirmed alpha.

Both former `best_submittable = _rank_best(all_pass_ids, conn)` lines replaced with `best_submittable = _apply_additivity_gate(client, all_pass_ids, conn)`.

Verification counts:
- `grep -c "_apply_additivity_gate" hunt.py` → 3 (1 def + 2 call sites)
- `grep -c "_rank_best(all_pass_ids" hunt.py` → 0

### Task 2 — test_phase4.py (two new integration tests)

Appended Phase 6 Plan 3 section after Phase 6 Plan 2 section. Both tests use `db.init_db(':memory:')`, zero real BRAIN API calls, patch at the `additivity` module level.

| Test | What it verifies |
|------|-----------------|
| `test_phase6_plan3_gate_blocks_nonaddititve` | `proxy_drop=True` → no survivors → `result=None`; `confirm_additive` NOT called |
| `test_phase6_plan3_gate_passes_additive` | `proxy_drop=False`, `additive=True` → `alpha_id` returned; `confirm_additive` called exactly once with correct `alpha_id` |

## Deviations from Plan

### Pre-completed Work

**Task 1 already committed** (db398a6) before this execution wave started. The prior wave's `06-03-PLAN.md` git status showed `M .planning/phases/06-additivity-gate/04-03-PLAN.md` which corresponds to hunt.py work committed as `feat(06-03)`. Task 2 (integration tests) was the remaining work — appended cleanly and committed as `a2f6747`.

No other deviations — plan executed as written.

## Verification Results

```
./venv/bin/python -m pytest test_phase4.py -k "phase6_plan3" --tb=short -x -q
2 passed, 46 deselected in 0.09s

./venv/bin/python -m pytest test_phase4.py -k "phase6" --tb=short -q
15 passed, 33 deselected in 0.07s

./venv/bin/python -m pytest test_phase4.py --tb=short -q
48 passed, 18 warnings in 0.10s   # zero regressions

grep -c "_rank_best(all_pass_ids" hunt.py
0

grep -c "_apply_additivity_gate" hunt.py
3
```

## Threat Surface Scan

No new network endpoints introduced. `_apply_additivity_gate` calls `additivity.confirm_additive` which reuses `grade.trigger_correlation_check` + `grade.poll_correlation` — both already in `grade.py` with existing auth patterns. T-06-09 mitigated: strict `result.additive is True` check. T-06-10 mitigated: sequential confirms, never in `grade_many` thread pool. T-06-11 mitigated: `confirm_additive` always issues fresh `/check` call.

## Commits

| Task | Commit | Message |
|------|--------|---------|
| Task 1 | `db398a6` | `feat(06-03): add _apply_additivity_gate to hunt.py at both best_submittable sites` |
| Task 2 | `a2f6747` | `test(06-03): add two integration tests for hunt additivity gate (phase6_plan3)` |

## Self-Check: PASSED

- `hunt.py` modified: confirmed present
- `test_phase4.py` modified: confirmed present
- Commit `db398a6` exists: yes
- Commit `a2f6747` exists: yes
- 2 `phase6_plan3` tests pass: yes (2 passed, 46 deselected)
- 15 total `phase6` tests pass: yes (15 passed, 33 deselected)
- Full suite regression: 48 passed, 0 failed
- `_rank_best(all_pass_ids` count in hunt.py: 0 (old pattern fully replaced)
- `_apply_additivity_gate` count in hunt.py: 3 (1 def + 2 call sites)
- `import additivity` present in hunt.py: yes (line 30)
