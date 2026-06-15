---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Additive Alpha Discovery
status: planning
stopped_at: Phase 7 context gathered
last_updated: "2026-06-15T14:32:59.959Z"
last_activity: 2026-06-15
progress:
  total_phases: 9
  completed_phases: 6
  total_plans: 27
  completed_plans: 27
  percent: 67
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-07)

**Core value:** Produce a decent, genuinely-submittable alpha — verified against BRAIN's own checks (never guessed) — while remembering every alpha tried so the system never repeats itself
**Current focus:** Phase 7 — brute force tool (tool b)

## Current Position

Phase: 7
Plan: Not started
Status: Ready to plan
Last activity: 2026-06-15

## Performance Metrics

**Velocity (v1.0 reference):**

- Total plans completed: 24
- Average duration: -
- Total execution time: -

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 5 | - | - |
| 02 | 4 | - | - |
| 03 | 6 | - | - |
| 04 | 6 | - | - |
| 06 | 3 | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*
| Phase 02-grounded-generation P01 | 260s | 2 tasks | 3 files |
| Phase 02-grounded-generation P02 | 305s | 2 tasks | 3 files |
| Phase 02-grounded-generation P04 | 900 | 2 tasks | 1 files |
| Phase 05-delay-0-feasibility-plumbing P01 | 25 | 3 tasks | 6 files |
| Phase 06 P01 | 8 | 2 tasks | 2 files |
| Phase 06-additivity-gate P02 | 20 | 2 tasks | 2 files |
| Phase 06-additivity-gate P03 | 5 | 2 tasks | 1 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Design verified 2026-06-07 by red-team agent — fixes folded in (SELF/PROD_CORRELATION endpoint, dynamic check limits, local validator, concurrency cap, schema additions)
- Phase 1 reuses wq_login.py (biometric login) and generalizes test_sim.py (replace hardcoded sharpe>1.25 with dynamic limit reads)
- Submission stays permanently manual — POST /alphas/{id}/submit is out of scope
- 2026-06-07: Phase 1 VERIFIED end-to-end live (sync/validate/grade/correlation). Baseline alpha qMXnEVQK graded clean through the full chain (Sharpe 1.62 / self_corr 0.346, all checks PASS)
- 2026-06-07: Improvement experiment (single-lever variants + stacking) produced winner C2 (alpha e7rnMqwp): winsorize(signal) × INDUSTRY neutralization — Sharpe 1.82 / Fitness 1.80 / self_corr 0.256; beats baseline on all 3 axes. Awaiting MANUAL submission by user in web UI
- 2026-06-11: grade.py fixed to record BRAIN's actual returned settings (not requested); 11 mislabeled delay-0→delay-1 DB rows corrected. This is the trigger for the whole v1.1 delay-0 effort.
- 2026-06-11: v1.1 design agreed — additivity is the objective, passing checks is the constraint; two decoupled tools share one BRAIN session (run one at a time); auto-submit stays OFF; ACE template shapes borrowed as inspiration only (not its runtime)
- 2026-06-12: probe_delay.py probe-gate created (D-04): probe_and_gate() fails fast with structured DelayCoercedError; run_probe() returns full ProbeResult diagnostic data; intentional coupling to grade._simulate_to_alpha avoids duplicating retry logic
- 2026-06-12: delay0_candidates.py created from run_delay0.py harvest (D-05): 8 _D0_CANDIDATES, 9 CLAIMED_DELAY0_FIELDS annotated as unverified hypothesis; run_delay0.py archived to archive/
- 2026-06-13: delay-0 EMPIRICALLY CONFIRMED feasible from code (Plan 05-03, verify_delay0.py). Test A sent _BASE_SETTINGS+delay:0; BRAIN returned delay=0 (real alpha e7rvXqwz). Test B/bisection skipped. The Plan 05-02 "payload/field defect" hypothesis is DISPROVEN — no change to probe_delay.py/delay0_candidates.py needed. Note: same sim sent maxTrade:"ON" but BRAIN returned "OFF" — BRAIN coerces some fields, just not delay. See 05-VERIFICATION.md.
- [Phase ?]: Archetype rotation via runs table row count (modulo 8) — deterministic since alphas.archetype is NULL for all 384 rows
- [Phase ?]: gather_insights restricted to sharpe/fitness/turnover/status and checks.result; archetype/self_corr/prod_corr excluded (NULL in-DB for all 384 rows)
- [Phase ?]: researcher.py seed tokens intersected against live catalog at build_thesis() to guarantee source_operators/source_datafields subset membership
- [2026-06-13 — REVERSED]: winsorize uses `std=` named param per BRAIN catalog definition `winsorize(x, std=4)`. The old "positional numeric arg" workaround (quick 260613-ldy) was WRONG — BRAIN rejects `winsorize(x, 4)` with "Invalid number of inputs: 2, should be exactly 1". validate.py now excludes named-arg keys (`name=` not `==`) from data-field checks, so `std=`/`dense=` validate cleanly. Also: grade.py now surfaces BRAIN's real sim ERROR message instead of mislabeling it "transient throttle/queue".
- [Phase ?]: nws12_afterhsz_sl VECTOR-type field always wrapped in vec_avg in ideator.py
- [Phase ?]: D-03 coercion warn+discard: grade_one returns early without db.upsert_alpha when BRAIN returns different delay than requested — mislabeled row failure mode structurally prevented
- [Phase ?]: D-04 probe guard: probe_and_gate fires only when delay != 1 AND max_sims > 0 — dry-run invocations never burn a probe sim slot

### Pending Todos

- **RESOLVED bug #5 (quick 260613-rvl):** `grade.py:160` 2nd delay-blind dedup fixed. `expr_exists` stays delay-blind (NULL-delay stubs must still match) but the duplicate-skip now only fires when the stored row's delay == effective_delay; different-delay matches fall through and simulate. Queued-stub inheritance preserved. 3 regression tests.
- **Minor:** clearing `pnl_cache/` files doesn't force re-backfill because `alphas.pnl_path` still set → backfill skips them. Null `pnl_path` too for a full refresh.
- delay-0 `/hunt` pipeline confirmed working end-to-end 2026-06-13 (first real delay-0 alpha 58vYLN21, Sharpe 0.37/fail). Finding a GOOD delay-0 alpha is now a search-breadth problem → Phase 6+. See memory [[delay0-hunt-pipeline-state]].
- Next direction (user 2026-06-13): set up remote-control, then start Phase 6 (additivity gate).

### Blockers/Concerns

- Biometric (Persona) re-auth is periodic; single-shot login only — a 401 stops the run and must surface rather than retry (never re-auth in loop)
- SDK simulate() `regular` param is buggy — always call simulate(expr) with default regular
- autobrain-sim lacks operators/datafields/check/submit — all must be hand-written against raw endpoints
- Two tools (hunt + bruteforce) share ONE BRAIN session; never two sim engines running simultaneously

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260611-l3w | Fix grade.py to record BRAIN's actual returned settings (not requested); correct 11 mislabeled delay-0→delay-1 DB rows | 2026-06-11 | b70c3fd | [260611-l3w-grade-actual-settings-fix](./quick/260611-l3w-grade-actual-settings-fix/) |
| 260613-kpu | Fix delay-blind novelty dedup (db.expr_exists/ideator/hunt now key on (expression, delay)) + selfcorr PnL parser (schema+records) — unblocks delay-0 hunt candidate generation | 2026-06-13 | 40dc170 | [260613-kpu-fix-delay-blind-novelty-dedup-and-selfco](./quick/260613-kpu-fix-delay-blind-novelty-dedup-and-selfco/) |
| 260613-ldy | Fix winsorize named-param (emit `winsorize(x, std=4)`; validate.py excludes named-arg keys) + grade.py surfaces real BRAIN sim ERROR instead of "throttle" mislabel — delay-independent, unblocks fundamental archetypes | 2026-06-13 | e93ab15 | [260613-ldy-fix-winsorize-named-param-std-in-ideator](./quick/260613-ldy-fix-winsorize-named-param-std-in-ideator/) |
| 260613-rvl | Make grade_one dedup delay-aware (bug #5): 2nd delay-blind expr_exists; duplicate-skip now keyed on (expression, effective_delay) while keeping NULL-delay queued-stub inheritance | 2026-06-13 | (this commit) | [260613-rvl-make-grade-py-grade-one-dedup-delay-awar](./quick/260613-rvl-make-grade-py-grade-one-dedup-delay-awar/) |

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Automation | AUTO-01: MCTS/genetic search | v2 | 2026-06-07 |
| Automation | AUTO-02: Headless Model-B daemon | v2 | 2026-06-07 |
| Infrastructure | Shared sim-queue for true Tool A+B simultaneity | v1.2 | 2026-06-11 |
| Learning | LLM learning/memory loop from brute-force survivors | v1.2 | 2026-06-11 |

## Session Continuity

Last session: 2026-06-15T14:32:59.949Z
Stopped at: Phase 7 context gathered
Resume file: .planning/phases/07-brute-force-tool-tool-b/07-CONTEXT.md
