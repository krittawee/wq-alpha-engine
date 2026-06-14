---
phase: 01-mvp-grading-engine
plan: "04"
subsystem: grading
tags: [grading, simulation, sqlite, worldquant, brain, correlation, autobrain-sim]

# Dependency graph
requires:
  - phase: 01-01
    provides: db.py with upsert_alpha, upsert_checks, expr_exists functions
  - phase: 01-02
    provides: sync.py with client._session hand-written endpoint pattern and BASE_URL
  - phase: 01-03
    provides: validate.py with validate(conn, expression) -> tuple[bool, str]
provides:
  - "grade.py: two-phase grader (Phase A: simulate + IS checks; Phase B: POST /check + correlation poll)"
  - "grade_one: dedupe → validate → simulate → IS checks → correlation → persist"
  - "grade_many: sequential/concurrent batch grader with concurrency cap ≤3"
  - "trigger_correlation_check: hand-written POST /alphas/{id}/check"
  - "poll_correlation: Retry-After polling until SELF/PROD_CORRELATION resolve"
affects: [01-05, cli.py, Phase 2 Ideator, Phase 3 Editor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-phase BRAIN grading: Phase A (SDK simulate) + Phase B (hand-written POST /check)"
    - "Dynamic IS check reading: iterate is.checks array; never hardcode thresholds"
    - "Retry-After polling: check header first, sleep if set, else raise_for_status"
    - "401-stops-run: raise_for_status() propagates everywhere; no re-auth in loop"
    - "Concurrency cap: min(max_workers, 3) enforced at grade_many entry"
    - "Parameterized SQL: all UPDATE/INSERT use ? placeholders; no BRAIN-data interpolation"

key-files:
  created:
    - grade.py
  modified: []

key-decisions:
  - "Both Phase A and Phase B implemented in grade.py; Phase B only triggered for IS survivors"
  - "grade_many sequential by default (max_workers=1); ThreadPoolExecutor path kept for Phase 2+"
  - "TimeoutError from poll_correlation caught gracefully; status set to 'timeout', corr fields stay None"
  - "simulate() called as client.simulate(expression) with no regular= keyword — SDK trap avoided"
  - "IS survivor determined dynamically: any FAIL (excluding PENDING) blocks; SELF/PROD_CORRELATION PENDING expected"
  - "__all__ added to declare public API surface explicitly"

patterns-established:
  - "Phase A uses SDK chain: client.simulate(expr) → sim.wait(verbose=False) → sim.get_alpha()"
  - "Phase B uses client._session for hand-written endpoints (SDK lacks /check)"
  - "Correlation poll mirrors brain_client.py Retry-After pattern from lines 234-246"
  - "All IS check limits read from BRAIN response; no hardcoded 1.25 or 0.7 in code"

requirements-completed: [ENG-04, ENG-05, ENG-06]

# Metrics
duration: 3min
completed: 2026-06-07
---

# Phase 01 Plan 04: Two-phase BRAIN grader with dynamic IS checks and correlation polling

**grade.py: two-phase grader — simulate → read is.checks dynamically from BRAIN (Phase A), then POST /alphas/{id}/check + Retry-After poll for SELF/PROD_CORRELATION (Phase B) — all persisted to alpha_kb.db with no hardcoded thresholds**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-06-07T02:05:05Z
- **Completed:** 2026-06-07T02:07:59Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- grade_one implements the full grading pipeline: dedupe check → local validation → simulate → dynamic IS check reading → Phase B correlation → SQLite persist
- IS checks are read dynamically from BRAIN's is.checks array; no thresholds hardcoded anywhere
- Phase B uses hand-written POST /alphas/{id}/check + Retry-After polling pattern from brain_client.py; TimeoutError handled gracefully
- All SQL in grade.py uses parameterized queries with ? placeholders — BRAIN-returned data never interpolated into SQL

## Task Commits

Each task was committed atomically:

1. **Task 1: Phase A — simulate + IS check reading** - `120ffca` (feat)
2. **Task 2: Phase B — correlation check and poll** - `73fd9a5` (feat)

## Files Created/Modified

- `grade.py` - Two-phase grader: grade_one, grade_many, trigger_correlation_check, poll_correlation

## Decisions Made

- simulate() called as `client.simulate(expression)` with expression as the only positional arg — never passing `regular=` keyword which would silently drop the expression (SDK trap)
- Phase B only triggered for IS survivors (is_survivor=True); non-survivors skip correlation entirely
- TimeoutError from poll_correlation caught in grade_one; status set to "timeout" so the alpha is still recorded
- grade_many is sequential (max_workers=1) by default for Phase 1; ThreadPoolExecutor bound to min(max_workers, 3) for future concurrent use
- is_survivor excludes PENDING results from FAIL check — SELF/PROD_CORRELATION are always PENDING after Phase A and are resolved in Phase B

## Deviations from Plan

None - plan executed exactly as written. Both Task 1 (Phase A) and Task 2 (Phase B) implemented as specified.

## Issues Encountered

None. All five final verification checks passed:
1. PHASE A STRUCTURE CHECK PASSED
2. PHASE B STRUCTURE CHECK PASSED
3. No `simulate.*regular=` in grade.py
4. No hardcoded thresholds (1.25, 0.7) in non-comment lines
5. `import grade` succeeds cleanly

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes beyond what the plan specified. grade.py uses client._session (existing auth) and parameterized SQL (no injection surface). 401 propagates immediately per T-04-01. No new packages added.

## Known Stubs

None. grade.py is fully wired: all four functions implemented, Phase B calling Phase A's alpha_id, SQLite UPDATE after correlation resolved.

## Next Phase Readiness

- grade.py is ready for cli.py (Plan 01-05) to import and call grade_many with a seed list
- grade_one handles all edge cases: duplicate, invalid, IS fail, correlation timeout
- grade_many summary table provides immediate feedback after each batch run

---
*Phase: 01-mvp-grading-engine*
*Completed: 2026-06-07*
