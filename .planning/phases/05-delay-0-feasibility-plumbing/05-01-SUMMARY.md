---
phase: 05-delay-0-feasibility-plumbing
plan: 01
subsystem: infra
tags: [delay-0, brain-api, coercion-detection, grade, hunt, researcher, simulation]

requires:
  - phase: 05-delay-0-feasibility-plumbing/05-02
    provides: probe_delay.probe_and_gate(), DelayCoercedError, _BASE_SETTINGS and _simulate_to_alpha interfaces

provides:
  - grade.py: delay param in grade_one/grade_many, D-03 coercion warn+discard, None-safe normalization, precedence warning
  - researcher.py: read_catalog and build_thesis accept delay param; queries correct datafields slice
  - find_alphas.py: delay param forwarded to build_thesis
  - hunt.py: --delay CLI flag; delay forwarded end-to-end; probe_and_gate wired before main loop (D-04)
  - test_phase4.py: 4 new coercion regression tests + updated test_grade_records_brain_actual_settings

affects:
  - Phase 06+ (delay-0 hunt/bruteforce can now request delay=0 via --delay 0; coercion is detected + discarded)
  - Any future caller of grade_one/grade_many (delay param is optional, default=1, fully backward-compat)

tech-stack:
  added: []
  patterns:
    - "Coercion warn+discard: grade_one returns {status: coerced} and skips db.upsert_alpha when BRAIN returns a different delay than requested"
    - "Defensive None normalization: int(x) only called when x is not None; absent BRAIN delay key falls back to requested delay"
    - "Precedence rule: settings['delay'] wins over delay= arg; warning emitted to stderr when both supplied and differ"
    - "Probe guard: probe_delay.probe_and_gate called only when delay != 1 AND max_sims > 0 — no probe on normal runs or dry runs"
    - "DelayCoercedError propagates unchanged out of hunt() — never swallowed"

key-files:
  created: []
  modified:
    - grade.py
    - researcher.py
    - find_alphas.py
    - hunt.py
    - .claude/commands/hunt.md
    - test_phase4.py

key-decisions:
  - "active_settings built as {**_BASE_SETTINGS, 'delay': delay} copy (never mutates module-level dict) — T-05-01 mitigation"
  - "Coercion returns early before db.upsert_alpha — structurally prevents the 11-mislabeled-rows failure mode from recurring (T-05-04 mitigation)"
  - "probe_and_gate guard: delay != 1 AND max_sims > 0 — skips probe on dry runs to avoid burning sim slots during argparse smoke tests (T-05-07 mitigation)"
  - "Test strategy: update test_grade_records_brain_actual_settings to no-coercion scenario (delay=1/delay=1) so recording assertion still passes after discard behavior was added"

patterns-established:
  - "End-to-end delay parameter threading: CLI --delay arg → hunt(delay=) → build_thesis(delay=) + grade_many(delay=) → grade_one(delay=) → active_settings → simulate"
  - "Pre-existing test_phase2 failures are unrelated to this plan (use real DB, return empty queueable set) — documented as out-of-scope"

requirements-completed: [DLY-01, DLY-02]

duration: 25min
completed: 2026-06-13
---

# Phase 5, Plan 01: Delay End-to-End Threading Summary

**Delay parameter threaded from CLI --delay through hunt/researcher/grade with D-03 coercion warn+discard and D-04 probe-gate guard before the main simulation loop**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-06-13T00:52:00Z
- **Completed:** 2026-06-13T01:17:00Z
- **Tasks:** 3 (Tasks 1 and 3 delivered together — tests committed with grade.py changes)
- **Files modified:** 6 (grade.py, researcher.py, find_alphas.py, hunt.py, hunt.md, test_phase4.py)

## Accomplishments

- grade_one(delay: int = 1) and grade_many(delay: int = 1): when settings=None, builds active_settings as {**_BASE_SETTINGS, "delay": delay} copy (never mutates module-level dict); precedence warning when settings and delay= arg both supplied and differ
- D-03 coercion guard: None-safe normalization at Step 5 (int(x) only when x is not None); if requested_delay_int != resolved_delay_int, prints COERCION WARNING to stderr with alpha_id + both delay values, returns {status: "coerced"} WITHOUT calling db.upsert_alpha
- researcher.read_catalog(delay: int = 1) parameterized; build_thesis(delay: int = 1) queries correct datafields slice and emits delay in returned dict
- find_alphas.find_alphas(delay: int = 1) forwards delay to build_thesis
- hunt.hunt(delay: int = 1): import probe_delay added; probe_and_gate wired with dual guard (delay != 1 AND max_sims > 0) before main loop; delay forwarded to build_thesis + both grade_many calls; DelayCoercedError propagates unchanged
- --delay CLI flag in hunt.py argparse; hunt.md updated with flag docs, dry-run note, updated hunt() invocation
- test_phase4.py: 5 tests updated/added (test_grade_coercion_warning, test_grade_no_coercion_when_delay_matches, test_grade_many_forwards_delay, test_grade_coercion_with_none_returned_delay, updated test_grade_records_brain_actual_settings); all 17 test_phase4.py tests pass

## Task Commits

1. **Task 1 + Task 3: grade.py delay param + coercion warn+discard + tests** - `131c1c9` (feat)
2. **Task 2: researcher/find_alphas/hunt threading + probe_and_gate + hunt.md** - `307b105` (feat)

**Plan metadata:** (final commit below)

## Files Created/Modified

- `/Users/winter.__.kor/quant/grade.py` — delay param in grade_one/grade_many, D-03 coercion warn+discard, None-safe normalization, precedence warning, import sys
- `/Users/winter.__.kor/quant/researcher.py` — read_catalog(delay=1) and build_thesis(delay=1) parameterized; datafields query uses WHERE delay=? bind
- `/Users/winter.__.kor/quant/find_alphas.py` — find_alphas(delay=1) forwards delay to build_thesis
- `/Users/winter.__.kor/quant/hunt.py` — import probe_delay; hunt(delay=1) with probe_and_gate guard; --delay argparse flag; delay forwarded end-to-end
- `/Users/winter.__.kor/quant/.claude/commands/hunt.md` — --delay flag documented; hunt() invocation updated; dry-run note added
- `/Users/winter.__.kor/quant/test_phase4.py` — 5 coercion regression tests; test_grade_records_brain_actual_settings updated to no-coercion scenario

## Decisions Made

- T-05-01: active_settings built as a copy (spread into new dict), never mutating grade._BASE_SETTINGS — eliminates the mutation-and-restore pattern from run_delay0.py
- T-05-04: Early return before db.upsert_alpha on coercion — the "11 mislabeled rows" failure mode is now structurally impossible
- T-05-07: probe guard fires only when delay != 1 AND max_sims > 0 — argparse smoke tests (--max-sims 0) never burn a probe sim slot
- Test strategy: updated test_grade_records_brain_actual_settings to use delay=1 request + BRAIN returns delay=1 (matched) so the recording assertion stays valid after the new discard behavior was added

## Deviations from Plan

None — plan executed exactly as written. All acceptance criteria verified. Task 3's tests were included in the Task 1 commit since grade.py changes and tests are tightly coupled (TDD RED+GREEN in one pass); the plan's structural split between Task 1 (grade.py) and Task 3 (tests) was preserved logically but committed together per project memory's "one bundled commit per task" policy.

## Issues Encountered

- `test_phase2.py::test_criterion_2_validator_rejects_zero` and `test_phase2.py::test_criterion_3_tagged_and_novel` fail — pre-existing failures confirmed unchanged since before this plan (test_phase2.py was not modified by this plan; failures use real alpha_kb.db and return empty queueable set). Documented as out-of-scope.

## Known Stubs

None — all delay threading is fully wired. No placeholders.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes. All changes are pure Python in existing modules. The stderr coercion warning (T-05-02) is intentional and accepted per plan threat register.

## Next Phase Readiness

- `python hunt.py --delay 0` is now a valid invocation; probe_and_gate will fire before the main loop to fail-fast if BRAIN coerces delay-0
- Plan 03 (live probe verification) can now test the full end-to-end path with real BRAIN sims
- grade_one correctly discards coerced alphas — the mislabeling failure mode is closed

---

## Self-Check

- [x] grade.py exists and has `delay: int = 1` in grade_one and grade_many
- [x] researcher.py exists and has `delay: int = 1` in read_catalog and build_thesis
- [x] hunt.py has `import probe_delay` and `delay: int = 1` in hunt()
- [x] find_alphas.py has `delay: int = 1` in find_alphas()
- [x] test_phase4.py has test_grade_coercion_warning, test_grade_no_coercion_when_delay_matches, test_grade_many_forwards_delay, test_grade_coercion_with_none_returned_delay
- [x] Task 1 commit 131c1c9 in git log
- [x] Task 2 commit 307b105 in git log
- [x] test_phase4.py: 17/17 pass
- [x] test_phase3.py: passes (no regressions introduced)

## Self-Check: PASSED

---
*Phase: 05-delay-0-feasibility-plumbing*
*Completed: 2026-06-13*
