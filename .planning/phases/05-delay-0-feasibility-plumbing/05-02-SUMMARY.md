---
phase: 05-delay-0-feasibility-plumbing
plan: 02
subsystem: infra
tags: [probe, delay-0, brain-api, coercion-detection, alpha-simulation]

requires:
  - phase: 05-delay-0-feasibility-plumbing/05-01
    provides: grade.py _BASE_SETTINGS and _simulate_to_alpha interface

provides:
  - probe_delay.py with probe_and_gate(), run_probe(), DelayCoercedError, ProbeResult
  - delay0_candidates.py with harvested _D0_CANDIDATES (8 expressions) and CLAIMED_DELAY0_FIELDS (9 fields)
  - archive/run_delay0.py (retired from project root per D-05)

affects:
  - 05-03 (Plan 03 uses probe_and_gate to verify delay-0 round-trip; run_probe for Test B diagnostics)
  - Phase 06-08 (delay-0 hunt and bruteforce use probe_and_gate as the feasibility gate before runs)

tech-stack:
  added: []
  patterns:
    - "Probe-gate pattern: fire one sentinel sim before a batch run to catch session-level coercion early"
    - "Non-throwing diagnostic wrapper (run_probe) + throwing gate (probe_and_gate) — same probe logic, two call semantics"
    - "settings_override kwarg: callers pass a UI-verbatim payload without bypassing the module"
    - "Never mutate grade._BASE_SETTINGS — always spread into a new dict"

key-files:
  created:
    - probe_delay.py
    - delay0_candidates.py
    - archive/run_delay0.py
  modified: []

key-decisions:
  - "Intentional coupling to grade._simulate_to_alpha (private): avoids duplicating retry/backoff/401-propagation logic"
  - "conn parameter reserved but unused: keeps call signature stable for future probe-result recording"
  - "CLAIMED_DELAY0_FIELDS annotated as unverified hypothesis (coexisted with delay-recording bug)"
  - "run_delay0.py archived via git mv (not hard-deleted): history preserved per D-05"

patterns-established:
  - "Probe-gate: probe_and_gate() fails fast on coercion; run_probe() returns full diagnostic ProbeResult"
  - "All delay-0 field/expression claims labelled as claimed, not confirmed, until live probe re-verifies"

requirements-completed: [DLY-01, DLY-02]

duration: 10min
completed: 2026-06-12
---

# Phase 5, Plan 02: Probe-Gate Module & Candidate Harvest Summary

**probe_delay.py probe-gate with structured DelayCoercedError + ProbeResult round-trip diagnostics; run_delay0.py harvested into delay0_candidates.py and archived per D-05**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-12T16:44:00Z
- **Completed:** 2026-06-12T16:47:42Z
- **Tasks:** 2
- **Files modified:** 3 (2 created, 1 moved to archive)

## Accomplishments

- Created probe_delay.py: probe_and_gate() raises DelayCoercedError when BRAIN coerces delay; run_probe() returns full ProbeResult without raising; both accept settings_override= kwarg for Test B callers
- DelayCoercedError carries structured requested_delay/returned_delay/alpha_id fields; ProbeResult carries full returned_settings + settings_sent round-trip data
- Harvested run_delay0.py's 8 candidate expressions and 9 field hypotheses into delay0_candidates.py with UNVERIFIED HYPOTHESIS annotation and "claimed" (not "confirmed") wording per D-05 caveat
- Retired run_delay0.py via git mv to archive/ — git history preserved, one delay-0 code path remains
- test_phase4.py: 13/13 pass (zero regressions)

## Task Commits

1. **Task 1: Create probe_delay.py** - `cbd8b9f` (feat)
2. **Task 2: Harvest run_delay0.py + retire** - `b6845fc` (feat)

**Plan metadata:** (final commit below)

## Files Created/Modified

- `/Users/winter.__.kor/quant/probe_delay.py` — probe_and_gate(), run_probe(), DelayCoercedError, ProbeResult, PROBE_EXPRESSION
- `/Users/winter.__.kor/quant/delay0_candidates.py` — _D0_CANDIDATES (8 expressions), CLAIMED_DELAY0_FIELDS (9 fields), post_test_b_update_note()
- `/Users/winter.__.kor/quant/archive/run_delay0.py` — retired from project root; full content preserved in archive/

## Decisions Made

- Coupled probe_delay.py to grade._simulate_to_alpha (private function): same project; avoids duplicating retry/backoff/401-propagation logic already encapsulated there.
- conn parameter accepted but unused in this version; reserved for future probe-result recording to alpha_kb.db.
- CLAIMED_DELAY0_FIELDS marked as unverified hypothesis because run_delay0.py coexisted with the delay-recording mislabeling bug (fixed 2026-06-11); these are hypotheses to re-confirm via probe, not ground truth.
- run_delay0.py archived via git mv (not deleted): git history preserved; archive/ comment directs future developers to delete the archive file if all candidates are confirmed dupes or invalidated.

## Deviations from Plan

None — plan executed exactly as written. All interface contracts honored (ProbeResult fields, DelayCoercedError structured fields, run_probe non-throwing, probe_and_gate raising, settings_override kwarg). Verification checks all passed.

## Issues Encountered

None. The venv activation is required for python import tests (requests not in system Python), but this is expected project setup, not an issue.

## Known Stubs

None — both files are complete. delay0_candidates.py's CLAIMED_DELAY0_FIELDS are intentionally marked as unverified hypotheses (not stubs); they will be re-confirmed by Plan 03 live probe.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced. probe_delay.py is a pure code module; both functions receive a pre-authenticated client and never call login().

## Next Phase Readiness

- Plan 03 (05-03) can now import probe_delay.probe_and_gate and probe_delay.run_probe directly
- run_probe() with settings_override= is the designed path for Test B bisection in Plan 03
- delay0_candidates._D0_CANDIDATES provides the candidate pool for Plan 03 verification

---

## Self-Check

- [x] probe_delay.py exists at /Users/winter.__.kor/quant/probe_delay.py
- [x] delay0_candidates.py exists at /Users/winter.__.kor/quant/delay0_candidates.py
- [x] archive/run_delay0.py exists at /Users/winter.__.kor/quant/archive/run_delay0.py
- [x] run_delay0.py NOT at project root
- [x] Task 1 commit cbd8b9f in git log
- [x] Task 2 commit b6845fc in git log
- [x] test_phase4.py: 13/13 pass

## Self-Check: PASSED

---
*Phase: 05-delay-0-feasibility-plumbing*
*Completed: 2026-06-12*
