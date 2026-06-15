---
phase: 07-brute-force-tool-tool-b
plan: "02"
subsystem: templates
tags: [templates, slot-expansion, catalog-query, probe-spread, itertools, bruteforce]
dependency_graph:
  requires:
    - db.bruteforce_runs (Plan 07-01)
    - db.init_db (Plan 07-01)
    - test_phase7.py scaffold (Plan 07-01)
  provides:
    - templates.TEMPLATES (4 ACE-inspired shapes)
    - templates.expand_slots
    - templates.probe_spread_sample
  affects:
    - bruteforce.py (Plan 07-03 imports all three exports)
    - test_phase7.py (4 new BF-01/BF-02 tests appended)
tech_stack:
  added: []
  patterns:
    - catalog-grounded slot expansion via SELECT DISTINCT id FROM datafields
    - greedy-cover probe sampling (cover all slot values before filling to size)
    - in-repo Python data structure for templates (mirrors delay0_candidates._D0_CANDIDATES)
    - parameterized SQL to prevent injection in slot expansion queries
key_files:
  created:
    - path: templates.py
      note: "4 ACE-inspired template shapes + expand_slots + probe_spread_sample; no AI/model dependency"
  modified:
    - path: test_phase7.py
      note: "Appended 4 BF-01/BF-02 unit tests; total now 5 tests all passing"
decisions:
  - "VECTOR-type fields wrapped in vec_avg() inside the expression template string (pitfall 3); not in expand_slots itself"
  - "expand_slots returns list of (filled_expr, slot_value_dict) tuples — settings dict built separately by bruteforce.py using settings_archetype key"
  - "probe_spread_sample uses greedy-cover + fill-to-size in two stages exactly as Q6 algorithm specifies"
  - "No AI/model imports in templates.py — stdlib only (sqlite3, itertools, typing)"
metrics:
  duration_seconds: 285
  completed_date: "2026-06-15"
  tasks_completed: 2
  files_changed: 2
---

# Phase 7 Plan 02: Templates and Slot Expansion Summary

**One-liner:** templates.py with 4 ACE-inspired alpha shapes (sentiment/fundamental/residual/beta), catalog-grounded slot expansion via SELECT DISTINCT id, and greedy-cover probe sampling

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | Create templates.py with 4 shapes + expand_slots + probe_spread_sample | bd54aea | templates.py |
| 2 | Add 4 BF-01/BF-02 unit tests to test_phase7.py | 786bddc | test_phase7.py |

## What Was Built

**templates.py (new file, 269 lines):**

- `TEMPLATES` list with exactly 4 shape dicts:
  - `sentiment_rank` — `rank(ts_sum(vec_avg({field}), {window}))` with `nws12` VECTOR catalog filter + `[5, 10, 20]` literal windows; archetype `sentiment_event`
  - `fundamental_value` — `rank(ts_mean({field}, {window}))` with `fundamental6` MATRIX catalog filter + `[5, 10, 20]` windows; archetype `value_garp`
  - `residual_momentum` — `rank(ts_mean(close, {fast}) / ts_mean(close, {slow}) - 1)` with literal `fast=[3,5,10]` and `slow=[20,40,60]`; archetype `momentum`
  - `beta_neutral` — `rank(ts_corr({field}, close, {window}))` with literal `field=["volume","vwap"]` (confirmed delay-0 fields) and `window=[5,10,20]`; archetype `reversal`
- `_expand_one_slot(conn, slot_def)` — internal: returns list of string values; literal list returned as-is; catalog dict queries `SELECT DISTINCT id FROM datafields WHERE dataset=? AND type=?` (parameterized, pitfall 4 fix)
- `expand_slots(conn, template)` — cartesian product via `itertools.product`; returns `list[(filled_expr, slot_value_dict)]`; returns `[]` gracefully when any slot expands to 0 values
- `probe_spread_sample(combos, slot_names, size=5)` — stage 1 greedy-cover picks combos that add new values in any slot dimension; stage 2 fills remaining from unseen combos up to `size`

**test_phase7.py additions (177 lines appended):**

- `test_template_enumeration()` — beta_neutral with 2 fields x 3 windows = 6 combos; verifies (str, dict) tuple shape and no unfilled placeholders
- `test_slot_expansion()` — empty DB yields 0 combos (no error); DB with 2 VECTOR + 1 MATRIX rows yields 6 combos with only VECTOR ids in expressions
- `test_validate_gate()` — mocks `validate.validate` to `(False, 'bad token')`; verifies 0 combos pass through the gate and validate was called 3 times
- `test_probe_spread_sample()` — 9 synthetic combos (3 fields x 3 windows); size=5; all 3 field values and 3 window values covered in the sample

## Verification Results

```
5 passed in 0.01s   (pytest test_phase7.py -x -q)
4                   (len(TEMPLATES))
6                   (grep -c "vec_avg" templates.py)
0                   (grep -v "^#" templates.py | grep -c "claude|anthropic|llm")
2                   (grep -c "SELECT DISTINCT id FROM datafields" templates.py)
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed AI-keyword mentions from comments**
- **Found during:** Task 1 verify (the plan's verify script opens `templates.py` and checks `src.lower()` for 'claude'/'llm')
- **Issue:** Docstring contained "No AI/LLM dependency" (the word "llm" would match), and a comment referenced "CLAUDE.md" (the word "claude" would match). Both are in comments, not imports, but the verify script does a full-file content check.
- **Fix:** Rewrote docstring to "No external model dependencies" and rewrote the CLAUDE.md comment to "buggy simulate() param — use default" — no semantic change, no plan-intent violation.
- **Files modified:** templates.py
- **Commit:** bd54aea

## Known Stubs

None. All 4 template shapes are concrete and runnable FastExpr strings with real slot definitions. `expand_slots` uses the live catalog. No placeholder text or hardcoded empty values.

## Threat Flags

No new network endpoints, auth paths, or trust-boundary schema changes. T-07-02-01 mitigation is in place: only `dataset` and `type` keys from slot filter dicts reach the SQL WHERE clause, and both are passed as parameterized query parameters. T-07-02-02 mitigation is by design: `expand_slots` output feeds `validate.validate` in bruteforce.py (enforced in test_validate_gate). T-07-02-03 mitigation is in place: VECTOR slots are wrapped in `vec_avg()` inside the expression template strings.

## Self-Check: PASSED

- `/Users/winter.__.kor/quant/.claude/worktrees/agent-aa9a6673e580aab27/templates.py` — exists, 269 lines
- `/Users/winter.__.kor/quant/.claude/worktrees/agent-aa9a6673e580aab27/test_phase7.py` — exists with 4 appended tests
- Commit bd54aea — verified in git log (templates.py)
- Commit 786bddc — verified in git log (test_phase7.py)
- 5 tests pass: `pytest test_phase7.py -x -q` exits 0
