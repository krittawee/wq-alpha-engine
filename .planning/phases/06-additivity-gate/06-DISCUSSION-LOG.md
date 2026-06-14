# Phase 6: Additivity Gate - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-13
**Phase:** 6-additivity-gate
**Areas discussed:** Proxy correlation method, Pre-filter behavior; (Book definition + Degraded-PnL handling locked by Claude's recommendation at user's request)

---

## Proxy correlation method

| Option | Description | Selected |
|--------|-------------|----------|
| Both signals | max-pairwise (predicts BRAIN self_corr gate) + corr-to-combined-book (true additivity); rank by combined-book | ✓ |
| Max-pairwise only | reuse selfcorr.max_pearson; simplest, mirrors self_corr, but not whole-book additivity | |
| Combined-book only | corr vs summed book PnL; faithful to objective but doesn't predict the max-pairwise gate | |

**User's choice:** Both signals.
**Notes:** User first asked "what about get correlation from brain api" — clarified the two-layer triage→confirm design: the local proxy reuses already-simulated PnL for free to rank/pre-filter; BRAIN's `/check` is the expensive authoritative confirm run only on finalists. User then confirmed "both signals."

---

## Pre-filter behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Soft pre-filter with margin | ranker first; hard-drop only when local corr is well above BRAIN's limit + margin | ✓ |
| Rank-only (no blocking) | proxy only sorts; BRAIN check is sole gate; safest but spends sims on losers | |
| Hard filter at the limit | drop anything over BRAIN's limit; saves most sims but false-drops borderline | |

**User's choice:** Soft pre-filter with margin.
**Notes:** Balances sim/`/check` budget against false-dropping genuinely-additive borderline candidates.

---

## Claude's Discretion (locked at user's "which one u recommend")

- **Book definition:** the user's submitted/active competition alphas only (objective = team competition score). Recommended and locked as D-03.
- **Degraded-PnL handling:** rank on available PnL + warn with skipped-count; never hard-refuse; fold in the `alphas.pnl_path`-null fix. Recommended and locked as D-04.
- Combined-book aggregation form (summed vs mean daily returns) and the numeric pre-filter margin left to planner/researcher; default to simplest faithful form, margin as a named constant derived from BRAIN's limit.

## Deferred Ideas

- CMD-01 (`/hunt --delay` ranks via gate) → Phase 8
- CMD-03 (`/iterate` decorrelate mode) → Phase 9
- Tool B (brute-force) gate integration → Phase 7
- Bug #5 (grade.py:160 second delay-blind dedup) → separate quick fix, tracked in STATE
