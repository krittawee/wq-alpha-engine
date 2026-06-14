---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Additive Alpha Discovery
status: planning
last_updated: "2026-06-12T00:00:00.000Z"
last_activity: 2026-06-12
progress:
  total_phases: 5
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-07)

**Core value:** Produce a decent, genuinely-submittable alpha — verified against BRAIN's own checks (never guessed) — while remembering every alpha tried so the system never repeats itself
**Current focus:** v1.1 — Additivity is the objective; passing the checks is the constraint

## Current Position

Phase: Phase 5 — Delay-0 Feasibility & Plumbing (not started)
Plan: —
Status: Roadmap defined; ready to plan Phase 5
Last activity: 2026-06-12 — v1.1 roadmap (Phases 5–9) written

## Performance Metrics

**Velocity (v1.0 reference):**

- Total plans completed: 21
- Average duration: -
- Total execution time: -

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 5 | - | - |
| 02 | 4 | - | - |
| 03 | 6 | - | - |
| 04 | 6 | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*
| Phase 02-grounded-generation P01 | 260s | 2 tasks | 3 files |
| Phase 02-grounded-generation P02 | 305s | 2 tasks | 3 files |
| Phase 02-grounded-generation P04 | 900 | 2 tasks | 1 files |

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
- [Phase ?]: Archetype rotation via runs table row count (modulo 8) — deterministic since alphas.archetype is NULL for all 384 rows
- [Phase ?]: gather_insights restricted to sharpe/fitness/turnover/status and checks.result; archetype/self_corr/prod_corr excluded (NULL in-DB for all 384 rows)
- [Phase ?]: researcher.py seed tokens intersected against live catalog at build_thesis() to guarantee source_operators/source_datafields subset membership
- [Phase ?]: winsorize uses positional numeric arg — std= keyword causes 'std' to be parsed as unknown data-field token by validate.py
- [Phase ?]: nws12_afterhsz_sl VECTOR-type field always wrapped in vec_avg in ideator.py

### Pending Todos

- Plan Phase 5 (delay-0 feasibility) first — smallest phase, gates the whole delay-0 bet

### Blockers/Concerns

- Biometric (Persona) re-auth is periodic; single-shot login only — a 401 stops the run and must surface rather than retry (never re-auth in loop)
- SDK simulate() `regular` param is buggy — always call simulate(expr) with default regular
- autobrain-sim lacks operators/datafields/check/submit — all must be hand-written against raw endpoints
- Two tools (hunt + bruteforce) share ONE BRAIN session; never two sim engines running simultaneously

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260611-l3w | Fix grade.py to record BRAIN's actual returned settings (not requested); correct 11 mislabeled delay-0→delay-1 DB rows | 2026-06-11 | b70c3fd | [260611-l3w-grade-actual-settings-fix](./quick/260611-l3w-grade-actual-settings-fix/) |

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Automation | AUTO-01: MCTS/genetic search | v2 | 2026-06-07 |
| Automation | AUTO-02: Headless Model-B daemon | v2 | 2026-06-07 |
| Infrastructure | Shared sim-queue for true Tool A+B simultaneity | v1.2 | 2026-06-11 |
| Learning | LLM learning/memory loop from brute-force survivors | v1.2 | 2026-06-11 |

## Session Continuity

Last session: 2026-06-12T00:00:00.000Z
Stopped at: v1.1 roadmap written (Phases 5–9); no phases planned yet
Resume file: .planning/ROADMAP.md (Phase 5 is next)
