# Roadmap: Grounded Alpha Discovery System

## Overview

Four phases build a self-researching WorldQuant BRAIN alpha pipeline. Phase 1 delivers
a pure-Python grading engine (no LLM) that syncs BRAIN's real catalog, validates
expressions locally, simulates them, reads every IS check limit straight from BRAIN,
resolves correlations via POST /check, and persists everything to SQLite. Phases 2–3
add the LLM loop (Researcher, Ideator, Editor agents). Phase 4 adds knowledge-driven
settings tuning, decay monitoring, and the Obsidian prose layer.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3, 4): Planned milestone work
- Decimal phases (e.g., 2.1): Urgent insertions added at runtime

- [x] **Phase 1: MVP Grading Engine** - Sync catalog + alphas to SQLite, local validator, two-phase BRAIN grading, persist — no LLM in loop
- [x] **Phase 2: Grounded Generation** - Researcher + Ideator agents reading verified catalog and memory to produce grounded FastExpr candidates (completed 2026-06-08)
- [x] **Phase 3: Smart Iteration** - Editor diagnose+mutate loop, memory-aware dedupe, local PnL pre-filter, Frequent Subtree Avoidance (completed 2026-06-10)
- [ ] **Phase 4: Optimization & Polish** - Knowledge-driven Settings Optimizer, decay monitor, Obsidian prose layer

## Phase Details

### Phase 1: MVP Grading Engine

**Goal**: A runnable engine that grades a hand-seeded expression list against BRAIN's real IS checks (including correlation), persists results to SQLite, and never re-authenticates inside the loop
**Depends on**: Nothing (first phase — reuses existing wq_login.py and test_sim.py)
**Requirements**: ENG-01, ENG-02, ENG-03, ENG-04, ENG-05, ENG-06, ENG-07
**Success Criteria** (what must be TRUE):

  1. Running `python sync.py` populates the `operators`, `datafields`, and `settings` tables in `alpha_kb.db` by reading BRAIN's API (no hardcoded catalog)
  2. Running `python grade.py ideas.txt` rejects any expression whose operators or fields are absent from the synced catalog before spending a simulation slot
  3. For each expression that passes local validation, the grader simulates it and reads every check's `result` and `limit` from BRAIN's `is.checks` array (no hardcoded 1.25 or 0.7)
  4. IS survivors trigger `POST /alphas/{id}/check`, poll until SELF_CORRELATION and PROD_CORRELATION leave PENDING, and persist both values to SQLite
  5. All grading runs at concurrency <=3 on one shared authenticated session with zero in-loop re-authentication calls; a 401 surfaces and stops the run rather than retrying

**Plans**: 5 plans

Plans:
**Wave 1**

- [x] 01-01-PLAN.md — SQLite data layer (db.py): schema + CRUD functions

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md — Catalog + existing-alpha sync (sync.py): /operators, /data-fields, /alphas
- [x] 01-03-PLAN.md — Local expression validator (validate.py): operator/field checks against catalog

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 01-04-PLAN.md — Two-phase grader (grade.py): simulate + IS checks + POST /check correlation

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 01-05-PLAN.md — CLI entrypoint (cli.py) + seed list (seeds.txt) + end-to-end checkpoint

### Phase 2: Grounded Generation

**Goal**: A Researcher agent produces a grounded thesis and an Ideator agent turns it into FastExpr candidates using only verified operators and fields, deduped against the DB
**Depends on**: Phase 1
**Requirements**: GEN-01, GEN-02
**Success Criteria** (what must be TRUE):

  1. Running `/find-alphas` (or equivalent Claude Code command) produces a thesis note in Obsidian that cites specific operators/fields from the synced catalog and at least one insight from past alpha results in SQLite
  2. The Ideator outputs expressions where every operator and data-field token is confirmed present in the `operators` / `datafields` tables — the local validator rejects zero Ideator outputs for unknown tokens
  3. Each generated expression is tagged with an archetype (e.g., reversal, momentum, value) and is confirmed absent from `alphas.expression` before being queued for grading

**Plans**: 4 plans

Plans:
**Wave 1**

- [x] 02-01-PLAN.md — researcher.py: catalog reads + past-alpha insight queries + deterministic archetype selection + thesis assembly

**Wave 2** *(blocked on Wave 1)*

- [x] 02-02-PLAN.md — ideator.py: 4-8 grounded FastExpr candidates, validate.validate gate + db.expr_exists dedup + inherited archetype + seeds.txt emit

**Wave 3** *(blocked on Wave 2)*

- [x] 02-03-PLAN.md — /find-alphas command + find_alphas.py orchestrator + alpha-kb/ vault scaffold + Obsidian thesis note + runs row (stops before grading)

**Wave 4** *(blocked on Wave 3)*

- [x] 02-04-PLAN.md — end-to-end checkpoint: test_phase2.py asserts all 3 success criteria + human-verify thesis note quality

### Phase 3: Smart Iteration

**Goal**: The Editor classifies and diagnoses BRAIN check outcomes, proposes targeted mutations with lineage tracking, and upstream filters eliminate cheap duplicates before spending simulation slots
**Depends on**: Phase 2
**Requirements**: ITR-01, ITR-02, ITR-03, ITR-04
**Success Criteria** (what must be TRUE):

  1. After grading, every alpha in SQLite carries a PASS/NEAR/FAIL status and a human-readable diagnosis identifying which specific BRAIN check failed and a proposed cause
  2. NEAR/FAIL alphas produce at least one mutated expression with `parent_alpha_id` set in SQLite, forming a traceable mutation lineage
  3. The local PnL-based self-correlation pre-filter eliminates known-duplicate candidates without triggering any BRAIN API call
  4. Before each Ideator run, Frequent Subtree Avoidance mines passing alphas for common structural motifs and the Ideator's prompt explicitly excludes those motifs — post-Phase-3 passing alphas show measurable structural diversity relative to Phase 2 results

**Plans**: 6 plans

Plans:
**Wave 1** *(independent — build in parallel)*

- [x] 03-01-PLAN.md — editor.py: classify_from_checks (NEAR/FAIL/PASS deterministic) + diagnose_and_mutate (LLM mutations with parent_alpha_id lineage)
- [x] 03-02-PLAN.md — selfcorr.py: PnL fetch/cache + Pearson pre-filter + backfill_active_pnl + selfcorr_limit from checks table
- [x] 03-03-PLAN.md — fsa.py: AST subtree mining + mine_frequent_motifs + filter_candidates + diversity_metric

**Wave 2** *(blocked on Wave 1)*

- [x] 03-04-PLAN.md — grade.py + find_alphas.py wiring: NEAR status vocab + selfcorr hooks A/B in grade_one + FSA filter + avoid-list injection in find_alphas

**Wave 3** *(blocked on Wave 2)*

- [x] 03-05-PLAN.md — hunt.py orchestrator (research→generate→grade→editor→bounded loop) + /hunt command + /iterate command
- [x] 03-06-PLAN.md — test_phase3.py: all 4 ROADMAP criterion tests (zero sim/login calls)

### Phase 4: Optimization & Polish

**Goal**: NEAR alphas get targeted settings tuning by archetype, metric degradation is tracked over time, and human-readable research prose in Obsidian is linked back to alpha_ids in SQLite
**Depends on**: Phase 3
**Requirements**: OPT-01, OPT-02, OPT-03
**Success Criteria** (what must be TRUE):

  1. For a NEAR alpha, the Settings Optimizer proposes <=4 settings variants drawn from archetype heuristics and past PASS settings in SQLite (never a blind grid sweep), simulates them, and records outcomes back to the DB
  2. The decay monitor queries the time-stamped `checks` table and surfaces any alpha whose key metrics have degraded across successive check runs
  3. An Obsidian note exists for every thesis run, every archetype, and every notable failure family, each referencing its associated `alpha_id`(s) from SQLite

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. MVP Grading Engine | 5/5 | Complete | 2026-06-07 |
| 2. Grounded Generation | 4/4 | Complete   | 2026-06-08 |
| 3. Smart Iteration | 6/6 | Complete   | 2026-06-10 |
| 4. Optimization & Polish | 0/TBD | Not started | - |
