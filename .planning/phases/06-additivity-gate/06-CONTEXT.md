# Phase 6: Additivity Gate - Context

**Gathered:** 2026-06-13
**Status:** Ready for planning

<domain>
## Phase Boundary

A reusable **additivity gate** that decides whether a candidate alpha *adds to the team competition score* (is decorrelated from the existing book), not merely whether it passes BRAIN's IS checks. Two layers:

1. **Cheap local proxy** (ADD-01) — estimates a candidate's correlation to the book from PnL already returned by its simulation, with **zero extra BRAIN calls**. Used to rank and pre-filter survivors.
2. **BRAIN confirm** (ADD-02) — for finalists only, calls `/alphas/{id}/check`, reads SELF_CORRELATION / PROD_CORRELATION from BRAIN's `is.checks` against BRAIN's own limits (no hardcoded threshold), returns a verdict.

Delivered as a new `additivity.py` module whose gate is callable both as a **rank-score (float)** and a **yes/no filter (bool)** (ADD-04), and is invoked by every submit-recommendation path so nothing is labeled submit-ready on IS checks alone (ADD-03).

**In scope:** the gate module + wiring into the existing `hunt.py` submit-recommendation path.
**Out of scope:** `/hunt --delay` selection wiring (CMD-01, Phase 8), `/iterate` decorrelate mode (CMD-03, Phase 9), brute-force (Tool B) integration (Phase 7).
</domain>

<decisions>
## Implementation Decisions

### Proxy correlation method (ADD-01)
- **D-01:** The local proxy computes **both** signals for each candidate: (a) **max-pairwise correlation** via the existing `selfcorr.max_pearson` (mirrors BRAIN's `self_corr` = max correlation to any single book alpha → predicts the BRAIN self_corr GATE), and (b) **correlation to the combined book PnL** (the candidate vs the summed daily-return series of the whole book → the true measure of team-score additivity). **Rank primarily by combined-book correlation** (the additivity objective); expose max-pairwise alongside so the gate can predict which finalists will fail BRAIN's self_corr check before spending the real `/check`.

### Pre-filter behavior (ADD-01 → sim/check budget)
- **D-02:** The proxy is **primarily a ranker** but applies a **soft pre-filter with a safety margin**: hard-drop a candidate only when its local proxy correlation sits **well above** BRAIN's self_corr limit (limit + margin), so obvious losers don't consume the ~2-min sim / `/check` budget while genuinely-additive borderline candidates are NOT false-dropped. The BRAIN `/check` remains the authoritative gate for everything that survives the pre-filter.

### Definition of "the book" (what we correlate against)
- **D-03:** "The book" = the user's **submitted / active competition alphas only** — not locally-passing candidates, not all rows in the DB. The objective is the *team competition score*, which is driven by what is actually submitted. The reference-PnL selection (`selfcorr.get_reference_pnl_paths`) must make this explicit (active/submitted set), not an incidental query.

### Degraded / missing PnL handling
- **D-04:** When PnL is unavailable for part of the book, the proxy **ranks on what's available and warns loudly** (surfacing a count of book alphas skipped for missing PnL) — it never hard-refuses, because the BRAIN `/check` is the authoritative gate and one stale cache entry must not block the whole gate. Fold in the small **`alphas.pnl_path`-null fix**: clearing `pnl_cache/` files alone doesn't force `backfill_active_pnl` to re-fetch because `pnl_path` is still set — null it so the book's PnL actually refreshes.

### Two-layer design clarification (locks the why)
- **D-05:** The local proxy and the BRAIN check are **triage → confirm**, not either/or. The proxy reuses the PnL each survivor's simulation already returned (free); BRAIN `/check` is a separate, slower, rate-limited operation run **only on finalists**. "No BRAIN call" in ADD-01 means *no additional* call beyond the sim that already happened.

### Claude's Discretion
- The exact combined-book aggregation (sum of book daily returns vs equal-weight mean) and the numeric pre-filter margin are left to the planner/researcher to choose sensibly; default to the simplest faithful form (summed daily returns; margin a small fixed fraction of BRAIN's limit) and make the margin a named constant, not a magic number.
- Date-overlap alignment between candidate and book PnL reuses the existing `selfcorr._date_overlap_returns` / `_pnls_to_daily_returns` helpers.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 6: Additivity Gate" — goal, dependencies, 4 success criteria (rank_by_proxy zero-BRAIN, confirm_additive via `/alphas/{id}/check`, gate on all submit paths, reusable score/filter)
- `.planning/REQUIREMENTS.md` — ADD-01, ADD-02, ADD-03, ADD-04 (additivity); ITR-03 (local PnL self-corr pre-filter); CMD-01/CMD-03 (downstream consumers, NOT this phase)

### Project constraints (BRAIN truth, no hardcoded limits)
- `CLAUDE.md` §Constraints — BRAIN is source of truth; self/prod correlation via `POST /alphas/{id}/check`; **never hardcode 1.25/0.7** — read limits from `is.checks`; ≤3 concurrent sims; never re-auth in-loop

### Reusable primitives (see code_context)
- `selfcorr.py`, `grade.py` — the local-proxy and BRAIN-check primitives this phase composes
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `selfcorr.max_pearson(candidate_path, reference_paths)` (selfcorr.py:325) — max pairwise correlation of a candidate's PnL against the book; directly the max-pairwise signal of D-01.
- `selfcorr.get_reference_pnl_paths(conn)` (selfcorr.py:288) — book PnL paths; D-03 makes its selection criterion explicit (submitted/active).
- `selfcorr.get_selfcorr_limit(conn)` (selfcorr.py:307) — reads BRAIN's self_corr limit from the DB (no hardcode); basis for the D-02 pre-filter margin.
- `selfcorr.load_returns` (268), `_pearson` (98), `_date_overlap_returns` (124), `_pnls_to_daily_returns` (70) — building blocks for the combined-book correlation of D-01.
- `grade.trigger_correlation_check(client, alpha_id)` (grade.py:502) + `grade.poll_correlation(...)` (grade.py:516) — the BRAIN `/check` round-trip for `confirm_additive` (ADD-02); reads SELF_CORRELATION/PROD_CORRELATION from `is.checks`.

### Established Patterns
- Graceful degrade (D-13): selfcorr/grade return `None`/`[]` on missing data rather than raising; the proxy must follow this (D-04).
- BRAIN-as-truth: limits come from `is.checks` / DB, never literals (CLAUDE.md). The pre-filter margin is derived from `get_selfcorr_limit`, not a constant threshold.

### Integration Points
- `hunt.py` — the only current submit-recommendation path (`best_submittable`). The gate plugs in here: withhold submit-ready unless `confirm_additive` passes (ADD-03). Build the module reusable so Phase 7 (bruteforce) and Phase 9 (/iterate) can call the same gate.
</code_context>

<specifics>
## Specific Ideas

- The motivating failure (why additivity is the objective, not a nice-to-have): submitting alpha `1Ygw09oz` passed every BRAIN check but **dropped the IQC2026-S2 team d1 score by ~112** because it was too correlated with the existing book. Phase 6 is the gate that prevents exactly this. (See memory: brain-delay-recording-mismatch / delay0-hunt-pipeline-state.)
- The delay-0 hunt pipeline now works end-to-end (2026-06-13); Phase 6's gate is what turns its check-passing output into *submittable-and-additive* output.
</specifics>

<deferred>
## Deferred Ideas

- **CMD-01** — `/hunt --delay` selecting/ranking results through the gate (vs Sharpe alone): Phase 8 (Evolve /hunt). Phase 6 only builds the reusable gate + wires the existing hunt output.
- **CMD-03** — `/iterate` decorrelate mode (search variants for the most-additive that still passes): Phase 9.
- **Tool B (brute-force) integration** — Phase 7 calls the same gate; not built here.
- **Bug #5** — `grade.py:160` second delay-blind dedup (skips delay-0 candidates matching delay-1 rows): a separate quick fix, tracked in STATE Pending Todos — NOT part of Phase 6, but worth doing before the next real hunt.

</deferred>

---

*Phase: 6-additivity-gate*
*Context gathered: 2026-06-13*
