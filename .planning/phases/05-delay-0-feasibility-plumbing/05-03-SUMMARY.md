---
phase: 05-delay-0-feasibility-plumbing
plan: 03
subsystem: verification
tags: [delay-0, brain-api, empirical-verification, coercion-detection, human-gated]

requires:
  - phase: 05-delay-0-feasibility-plumbing/05-02
    provides: probe_delay.run_probe() / ProbeResult / DelayCoercedError
  - phase: 05-delay-0-feasibility-plumbing/05-01
    provides: grade._BASE_SETTINGS with delay threaded through

provides:
  - verify_delay0.py — human-gated single-process Test A/Test B verification script (committed 2b2e213)
  - 05-VERIFICATION.md — empirical probe verdict record (Test A PASS, delay=0 confirmed)
  - EMPIRICAL FINDING — delay-0 is feasible directly from code; no payload/field fix needed

affects:
  - Phase 06-08 (delay-0 hunt and bruteforce: feasibility gate is GREEN — _BASE_SETTINGS path works for delay-0)
  - probe_delay.py / delay0_candidates.py (NO change required — Test A passed, Test B/bisection never reached)

tech-stack:
  added: []
  patterns:
    - "Human-gated live experiment: single login() at top, sequential sims, partial results flushed to disk after every sim so a 401 never loses data"
    - "Verify-actual-vs-requested: read BRAIN's RETURNED delay/settings, never trust the request"

key-files:
  created:
    - .planning/phases/05-delay-0-feasibility-plumbing/05-VERIFICATION.md
  modified: []

key-decisions:
  - "Test A used the default minimal-change path (_BASE_SETTINGS + delay:0) so the path verified IS the path future code uses"
  - "Test B + independent bisection were correctly NOT reached — Test A PASS made fallback unnecessary"
  - "No change to probe_delay.py / delay0_candidates.py: the earlier payload/field-defect hypothesis is disproven"

patterns-established:
  - "delay-0 feasibility is confirmed GREEN from code — future delay-0 work needs no special payload matching"
  - "Standing rule retained: always verify BRAIN's returned delay == requested before trusting a delay-0 label"

requirements-completed: [DLY-01, DLY-02]

duration: ~2min (one sim)
completed: 2026-06-13
---

# Phase 5, Plan 03: Empirical Delay-0 Verification Summary

**verify_delay0.py fired one live BRAIN sim with our proven _BASE_SETTINGS + delay:0; BRAIN returned delay=0 (real delay-0 alpha e7rvXqwz). Test A PASS — delay-0 confirmed feasible from code, no settings fix required, Test B skipped.**

## Performance

- **Duration:** ~2 min (single Test A simulation)
- **Completed:** 2026-06-13
- **Tasks:** 1 (run the human-gated verification experiment)
- **Sims fired:** 1 (Test A only; Test B + bisection never reached)

## Accomplishments

- Ran verify_delay0.py end-to-end live: one Persona login, then a single Test A probe sim via probe_delay.run_probe()
- **Test A PASS:** sent `_BASE_SETTINGS` with `delay:0`; BRAIN returned `delay=0` — a genuine delay-0 alpha (`e7rvXqwz`)
- Test B (UI-verbatim payload) and the three-way independent bisection were correctly skipped — Test A's pass made fallback unnecessary
- 05-VERIFICATION.md written with full round-trip diagnostics (settings sent, settings returned, alpha id, verdict, conclusion); rewritten after the sim per partial-result-safety design
- **Overturns the prior assumption** that no genuine delay-0 pass exists / that delay-0 was unreachable from code — that was a recording bug (fixed 2026-06-11), not a capability limit

## Task Commits

1. **verify_delay0.py (script)** — `2b2e213` (feat, committed before the run)
2. **05-VERIFICATION.md + plan closeout (SUMMARY, STATE, ROADMAP)** — this commit (docs)

## Files Created/Modified

- `/Users/winter.__.kor/quant/.planning/phases/05-delay-0-feasibility-plumbing/05-VERIFICATION.md` — probe verdict record: Test A PASS, BRAIN returned delay=0, alpha e7rvXqwz, Test B skipped
- `verify_delay0.py` — already committed (2b2e213); the experiment driver

## Decisions Made

- Verified the default minimal-change path (`_BASE_SETTINGS` + `delay:0`) rather than the UI-verbatim payload first, so the verified path is identical to the path future delay-0 code will use.
- Did NOT modify probe_delay.py or delay0_candidates.py: the Plan 05-02 "payload/field defect" hypothesis is disproven — our standard settings already produce delay=0.

## Deviations from Plan

None on the must-have axis. The plan's primary path (Test A) passed, so the conditional Test B branch (D-02 bisection) was intentionally not executed — exactly as the plan specifies ("Test B, fallback, only if A is coerced").

## Issues Encountered

None. One subtle confirmation of the verify-actual pattern: the same sim **sent** `maxTrade:"ON"` but BRAIN **returned** `maxTrade:"OFF"` — BRAIN silently coerces some fields, just not `delay`. This is why reading returned settings (not trusting the request) is the correct pattern.

## Known Stubs

None.

## Threat Flags

None — verify_delay0.py calls login() exactly once at the top, fires sims sequentially (well under the ≤3 concurrency cap), uses run_probe (no DB persistence to alpha_kb.db), and lets a 401 propagate. No new endpoints, auth paths, or schema changes.

## Next Phase Readiness

- **Phase 5 feasibility gate is GREEN** — delay-0 is usable from code with no special payload matching
- Phases 06-08 (delay-0 hunt / bruteforce) can proceed on the assumption that `--delay 0` produces real delay-0 alphas
- Standing guard retained: probe_and_gate / the grade resolution block still verify returned delay per sim; this experiment confirms they will see delay=0 on the happy path

---

## Self-Check

- [x] 05-VERIFICATION.md exists and contains "BRAIN returned delay=0"
- [x] Test A verdict recorded as PASS with real alpha id (e7rvXqwz)
- [x] verify_delay0.py committed (2b2e213)
- [x] probe_delay.py / delay0_candidates.py unchanged (no fix needed)
- [x] DLY-01, DLY-02 satisfied

## Self-Check: PASSED

---
*Phase: 05-delay-0-feasibility-plumbing*
*Completed: 2026-06-13*
