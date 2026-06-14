# Phase 3: Smart Iteration - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning
**Source:** Human decisions resolved via /gsd:discuss-phase (AskUserQuestion)

<domain>
## Phase Boundary

Phase 3 adds an **Editor** plus two **upstream cheap filters** to the existing
flat-Python + Claude-command pipeline (Phase 1 grading engine, Phase 2 grounded
generation). It closes the research → ideate → grade → **diagnose → mutate → grade**
loop with diversity awareness.

**In scope:**
- **Editor** (hybrid): classify each graded alpha PASS/NEAR/FAIL, diagnose which
  BRAIN check failed and why, propose validated expression mutations with
  `parent_alpha_id` lineage, and run a *bounded autonomous* mutate→grade loop.
- **Local PnL self-correlation pre-filter**: a pre-sim parent-PnL proxy gate +
  a post-sim/pre-BRAIN-check precise filter that eliminates duplicates locally
  without spending the BRAIN correlation call.
- **Frequent Subtree Avoidance (FSA)**: mine over-used structural motifs from
  passing alphas (AST subtree mining) and steer generation toward novelty via a
  post-generation filter + LLM prompt injection.
- A new **`/hunt`** chained autonomous command — the headline deliverable — that
  runs **research → generate → grade → diagnose → mutate → grade**, hands-off,
  inside a configurable budget, and returns the best new submittable alpha found.
- A new **`/iterate`** Claude Code command as the standalone Editor entry point
  (operates on already-graded alphas, for controlled/manual use).

**Out of scope (do NOT build):** Settings Optimizer / parameter tuning, decay
monitor, Obsidian prose/Archetypes layer (all Phase 4 — OPT-01..03). Re-architecting
the deterministic Ideator into an LLM. Changing BRAIN auth or concurrency model.

**Requirements:** ITR-01, ITR-02, ITR-03, ITR-04
</domain>

<decisions>
## Implementation Decisions (LOCKED — human-resolved 2026-06-09)

### Editor architecture (ITR-01, ITR-02)
- **D-01: Hybrid Editor.** Deterministic code reads the `checks` table, classifies
  PASS/NEAR/FAIL, and identifies exactly which check broke and by how much. An LLM
  writes the human-readable "why" diagnosis and proposes mutations. (Mirrors the
  Phase 2 Researcher hybrid pattern.)
- **D-02: 1–3 mutations per NEAR and per FAIL alpha.** Both NEAR and FAIL statuses
  produce mutations (satisfies ROADMAP criterion 2). Each mutation row records
  `parent_alpha_id` for traceable lineage.
- **D-03: Mutations are validated, invalids dropped.** Every LLM-proposed mutation
  passes `validate.py` (verified operators/fields only) AND `db.expr_exists` dedup
  before persistence/queueing. Invalid or duplicate mutations are silently dropped.
  Reuses Phase 1/2 gates exactly — strongest grounding guarantee.
- **D-04: Editor auto-queues mutations into grading** (autonomous loop — a
  deliberate divergence from Phase 2's human-in-the-loop `/find-alphas`).
  **CONSTRAINT:** the loop MUST respect ≤3 concurrent sims and single-shot auth —
  **never re-auth in-loop** (CLAUDE.md). Reuse `grade_many`'s existing concurrency cap.

### NEAR vs FAIL classification (ITR-01)
- **D-05: NEAR margin = within 20% of limit.** A failing numeric check counts toward
  NEAR only if its `value` is within 20% of its `limit`.
- **D-06: Any structural/hard fail → FAIL.** Non-numeric / boolean checks (e.g.
  CONCENTRATED_WEIGHT, units, pyramid/theme matches) that fail force FAIL regardless —
  NEAR is reserved for purely numeric near-misses.
- **D-07: NEAR fail-count cap = at most 2.** NEAR requires ≤2 failing numeric checks,
  all within the 20% margin, and no hard/structural fail. (Catches the common
  correlated Sharpe+fitness near-miss; rejects broadly-weak alphas.)

### Local self-correlation pre-filter (ITR-03)
- **D-08: Two-stage filter.** (a) A pre-sim **parent-PnL proxy gate** — before
  simulating a mutation, if its already-graded parent is too correlated to a
  reference alpha, skip that lineage; (b) a post-sim **/ pre-BRAIN-check precise
  filter** — after a candidate is simulated (PnL available), compare locally before
  calling BRAIN's `POST /alphas/{id}/check`; if locally too-correlated, mark
  duplicate and skip the BRAIN correlation call.
- **D-09: Reference set = submitted alphas + all PASS alphas in DB** (skip FAILs).
  Submitted alphas mirror BRAIN's real self-corr; PASS alphas stop the autonomous
  loop from rediscovering itself.
- **D-10: Method = Pearson on daily PnL**, calibrated against BRAIN's stored
  `self_corr` values for already-checked alphas (compare local computation to BRAIN's
  reported number to validate the method/date-window).
- **D-11: Cutoff derived from BRAIN's SELF_CORRELATION limit** read from the `checks`
  table (optionally minus a small safety margin) — **never hardcode 0.7** (CLAUDE.md).
- **D-12: PnL fetch = backfill submitted once + lazy-cache passers.** One-time
  backfill of the ~16 submitted alphas' PnL up front (cached to `pnl_path`), then
  lazy-cache each PASS alpha's PnL right after grading. Never re-download if
  `pnl_path` is already set.
- **D-13: Graceful degradation.** If PnL can't be obtained for a candidate/reference,
  skip the local filter for that item and fall back to BRAIN's `POST /check` as the
  source of truth. The local filter is an optimization, never a correctness gate.

### Frequent Subtree Avoidance (ITR-04)
- **D-14: AST subtree mining.** Parse each PASS alpha's FastExpr into an expression
  tree, abstract away specific fields/numbers, enumerate subtree shapes, count
  frequency across passers, flag those above a frequency threshold. (Only option
  that is truly structural and yields the diversity metric the success criterion
  needs. A small FastExpr parser is also reusable for Editor mutation validation.)
- **D-15: Filter + LLM steer (both).** A post-generation structural **filter** drops/
  deprioritizes Ideator candidates whose AST contains a frequent motif (the hard
  guarantee on the deterministic Ideator), AND the mined avoid-list is injected into
  the **Researcher thesis prompt + Editor mutation prompt** (the LLM components that
  have prompts) to aim for novelty upstream. Filter is the non-negotiable core; LLM
  steer is the cheap bonus.

### Autonomous loop control
- **D-16: Stop on depth OR budget OR dry — NOT on first success.** The mutate→grade
  loop stops when ANY of: max generation depth reached, total sim budget exhausted,
  or a generation produces no new NEAR alphas. It does **not** early-stop when the
  first submittable alpha appears — it spends the budget hunting for a stronger one.
- **D-17: Budget is a configurable ceiling; default = 2 generations, ~30 sims/run**
  (≈20 min wall at 3 concurrent). User can raise it (e.g. 100/300 sims) so the loop
  "keeps going" as long as the auth session is alive. The ceiling exists ONLY to
  respect single-shot auth + BRAIN throttle (CLAUDE.md) — the loop can never run
  truly unbounded/forever, and never re-auths in-loop.
- **D-20: Hunt return value = best NEW submittable alpha.** Across the whole run,
  the loop returns the single highest-performing alpha that is (a) new/non-duplicate
  and (b) passes ALL BRAIN checks (IS survivor + self/prod correlation) — i.e.
  genuinely submittable. Ranking metric (Sharpe/fitness) is Claude's discretion.
  If no new submittable alpha is found within budget, it reports the best NEAR
  candidates + stops cleanly for re-run.

### Entry point / integration
- **D-18: TWO commands.**
  - **`/hunt` (headline)** — chained, hands-off autonomous run: research → generate
    (with FSA) → grade (with self-corr filter) → Editor diagnose/mutate → bounded
    loop → returns best new submittable alpha (D-20). No human stop in this mode.
    This is the "run it and walk away until a new high-point alpha emerges" command
    the user actually wants.
  - **`/iterate`** — standalone Editor entry point over *already-graded* alphas, for
    controlled/manual use. Mirrors `/find-alphas`' command pattern.
  - Phase 2's **`/find-alphas` (human-stop) stays as-is** for fully-manual control;
    `/hunt` reuses the same Researcher/Ideator + grade + Editor internals, just
    chained without the human checkpoint.
- **D-19: Each filter lands where its trigger already is.** Self-corr filter
  integrates into the `grade.py` pipeline (pre-BRAIN-check) + the proxy gate before
  sim; FSA mines + filters inside the generation path (before each Ideator run) and
  feeds the avoid-list to Researcher/Editor prompts. Both `/hunt` and `/find-alphas`
  exercise this same generation path.

### Claude's Discretion
- FSA "frequent" threshold (e.g. ≥X% of passers) and the cold-start min-sample guard
  (behavior when too few PASS alphas exist to mine meaningfully).
- Exact PnL caching mechanics (storage format under `pnl_path`, alignment of daily
  vectors, date-window handling pending researcher confirmation).
- Internal module structure (e.g. `editor.py`, `selfcorr.py`, `fsa.py` as standalone
  modules imported by the grade/generation/iterate entry points), LLM prompt wording.
- FastExpr parser implementation details.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap & requirements
- `.planning/ROADMAP.md` — Phase 3 goal + 4 success criteria (classification/diagnosis,
  mutation lineage, local self-corr pre-filter, FSA structural diversity).
- `.planning/REQUIREMENTS.md` — ITR-01..04 definitions.

### Phase 2 context to build on
- `.planning/phases/02-grounded-generation/02-CONTEXT.md` — Researcher hybrid pattern,
  deterministic Ideator decision, `/find-alphas` human-stop, archetype inheritance,
  `runs` table ownership; explicitly defers self-corr/FSA/Editor to THIS phase.
- `.planning/phases/02-grounded-generation/02-GROUNDING.md` — verified catalog
  inventory, Phase 1 integration contract, archetype taxonomy.

### Phase 1/2 code to integrate with (READ before implementing)
- `db.py` — `alphas` table already has `parent_alpha_id`, `status`, `pnl_path`,
  `self_corr`, `prod_corr`, `corr_checked_at`; `checks` table stores
  `name/result/value/limit_val` from BRAIN `is.checks`. Helpers: `init_db`,
  `upsert_alpha`, `upsert_checks`, `expr_exists`.
- `grade.py` — `grade_one`, `grade_many` (concurrency cap, per-thread SQLite conns),
  IS-checks survivor logic, `trigger_correlation_check` / `poll_correlation`
  (`GET /alphas/{id}/check`), current status vocabulary (`pass`/`fail`/`duplicate`/
  `invalid`/`timeout`/`error` — NEAR must be added). NOTE: `pnl_path` is currently
  always None — PnL download must be built.
- `ideator.py` — DETERMINISTIC template variant functions (`_make_*_variants`,
  `_VARIANT_FNS` dispatch, `_compose_expressions`, `generate_candidates`,
  `queueable`). No LLM prompt — FSA must hook here (filter) + upstream (Researcher).
- `researcher.py` — LLM thesis component (avoid-list injection target for FSA).
- `validate.py` — `validate(conn, expr) -> (bool, reason)` gate for mutations.
- `cli.py` / `find_alphas.py` — existing grading + generation entry points.
- `wq_login.py` — `login()` single-shot auth (never re-auth in-loop).

### Project constraints
- `CLAUDE.md` — single-shot auth / never re-auth in-loop, ≤3 concurrent sims, never
  hardcode check limits (read from BRAIN `is.checks`), SDK `simulate(regular=...)`
  trap, read each check's `result`/`limit` from BRAIN as source of truth.
- `docs/plans/2026-06-07-alpha-system-design.md` — overall system design.

### Research to confirm (researcher MUST resolve before planning)
- BRAIN's exact SELF_CORRELATION definition + the PnL endpoint
  (e.g. `GET /alphas/{id}/recordsets/pnl`) and its date-window — needed for D-10/D-12.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `alphas` schema: `parent_alpha_id`, `status`, `pnl_path`, `self_corr` columns
  already exist — lineage (ITR-02) and PnL caching (ITR-03) need no migration.
- `checks` table: `value` + `limit_val` per check — directly powers NEAR/FAIL margin
  math (D-05..07) with no new BRAIN calls.
- `grade_many`: concurrency-capped, thread-safe parallel grading — reuse for the
  autonomous loop (D-04) instead of writing new sim orchestration.
- `validate.py` + `db.expr_exists`: ready-made mutation safety gates (D-03).

### Established Patterns
- Hybrid LLM+deterministic split (Researcher) — the model for the Editor (D-01).
- Flat Python modules + thin Claude Code command orchestration (`/find-alphas`) —
  the model for `/iterate` (D-18).

### Integration Points
- Self-corr filter → inside `grade.py` (pre-`POST /check`) + proxy gate pre-sim (D-19).
- FSA → inside `/find-alphas` generation path, before each Ideator run; avoid-list
  → Researcher + Editor prompts (D-15, D-19).
- NEAR status → extend `grade.py` status vocabulary + classification logic.
</code_context>

<specifics>
## Specific Ideas

- Calibration approach for D-10: because `alphas.self_corr` stores BRAIN's reported
  value, compute local Pearson on cached PnL for those same alphas and compare —
  if local ≈ BRAIN, trust the pre-filter; if off, adjust method/date-window.
- "Generations" mental model for the loop (D-16/D-17): Gen 0 = initial candidates,
  Gen N = mutations of NEAR/FAIL from Gen N-1; depth cap = 2.
- Diversity metric for ROADMAP criterion 4: motif-frequency concentration of passing
  alphas before vs after Phase 3 (top-motif share should drop measurably).
</specifics>

<deferred>
## Deferred Ideas

- Settings Optimizer / parameter tuning, decay monitor, Obsidian prose/Archetypes
  layer → Phase 4 (OPT-01..03).
- Richer FSA (cross-archetype motif analysis, weighted novelty scoring) beyond the
  threshold-based avoid-list → future enhancement if diversity metric demands it.
</deferred>

---

*Phase: 03-smart-iteration*
*Context gathered: 2026-06-09*
