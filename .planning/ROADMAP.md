# Roadmap: Grounded Alpha Discovery System

## Overview

Four phases build a self-researching WorldQuant BRAIN alpha pipeline. Phase 1 delivers
a pure-Python grading engine (no LLM) that syncs BRAIN's real catalog, validates
expressions locally, simulates them, reads every IS check limit straight from BRAIN,
resolves correlations via POST /check, and persists everything to SQLite. Phases 2–3
add the LLM loop (Researcher, Ideator, Editor agents). Phase 4 adds knowledge-driven
settings tuning, decay monitoring, and the Obsidian prose layer.

**v1.1 (Phases 5–9)** reframes the goal: additivity is the objective, passing checks is
the constraint. Adds delay-0 support with coercion detection, the additivity gate (local
PnL proxy + real BRAIN correlation confirm), a standalone brute-force generation tool
(Tool B), evolved `/hunt` + `/iterate`, and `/iterate`'s new decorrelate mode.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3, 4): Planned milestone work
- Decimal phases (e.g., 2.1): Urgent insertions added at runtime

- [x] **Phase 1: MVP Grading Engine** - Sync catalog + alphas to SQLite, local validator, two-phase BRAIN grading, persist — no LLM in loop
- [x] **Phase 2: Grounded Generation** - Researcher + Ideator agents reading verified catalog and memory to produce grounded FastExpr candidates (completed 2026-06-08)
- [x] **Phase 3: Smart Iteration** - Editor diagnose+mutate loop, memory-aware dedupe, local PnL pre-filter, Frequent Subtree Avoidance (completed 2026-06-10)
- [x] **Phase 4: Optimization & Polish** - Knowledge-driven Settings Optimizer, decay monitor, Obsidian prose layer (completed 2026-06-11)
- [x] **Phase 5: Delay-0 Feasibility & Plumbing** - Confirmed BRAIN runs delay-0 from code (Test A PASS, alpha e7rvXqwz); coercion detection wired; `--delay` threaded end-to-end (completed 2026-06-13)
- [x] **Phase 6: Additivity Gate** - Local PnL correlation proxy to rank candidates + real BRAIN correlation confirm; reusable as filter and as score (completed 2026-06-15)
- [ ] **Phase 7: Brute-Force Tool (Tool B)** - In-repo template enumeration, local validate, probe-sim, bulk-sim, additivity gate; fully standalone; no AI dependency
- [ ] **Phase 8: Evolve /hunt + Fold /find-alphas** - Add `--delay`, additivity-gated selection to /hunt; retire /find-alphas as `/hunt --research-only`
- [ ] **Phase 9: /iterate Decorrelate Mode** - Given a passing alpha, search neutralization/settings/mutation variants for the most-additive one that still passes all checks

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

**Plans**: 6 plans

Plans:
**Wave 1** *(independent — build in parallel)*

- [x] 04-01-PLAN.md — grade.py + db.py prerequisite changes: settings param in grade_one/grade_many/_simulate_to_alpha + checks_history DDL + append_checks_history + note_path migration
- [x] 04-02-PLAN.md — test_phase4.py scaffold: 12 unit tests covering all 3 OPT requirements (zero BRAIN API calls)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 04-03-PLAN.md — optimizer.py + optimize.py: ARCHETYPE_HEURISTICS + build_variants + run_optimize + /optimize CLI
- [x] 04-04-PLAN.md — decay_monitor.py + decay.py: detect_decay + run_decay + /decay CLI
- [x] 04-05-PLAN.md — obsidian.py: regen_archetype_notes + regen_failure_notes + write_decay_note + regen_all + note_path DB update

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 04-06-PLAN.md — command files (.claude/commands/optimize.md, decay.md) + full test suite run + human-verify checkpoint (all 3 ROADMAP criteria)

### Phase 5: Delay-0 Feasibility & Plumbing

**Goal**: Confirmed that BRAIN actually runs delay-0 from code (not silently coerced to delay-1), with coercion detection wired in and `--delay` threaded through the full pipeline
**Depends on**: Phase 4
**Requirements**: DLY-01, DLY-02
**Success Criteria** (what must be TRUE):

  1. Running a single delay-0 simulation from code and inspecting BRAIN's returned settings shows `delay=0` — if BRAIN returns `delay=1` instead, the discrepancy is logged as a coercion warning before the phase proceeds
  2. `grade.py` (and any downstream grading path) compares the requested delay against the value in BRAIN's returned settings object and raises a visible warning whenever they differ — the recorded DB row always stores BRAIN's actual returned delay, never the requested value
  3. `/hunt --delay 0` and `/bruteforce --delay 0` (once built) pass the delay parameter end-to-end from the CLI to the simulate call without silent override

**Plans**: 3 plans

Plans:
**Wave 1**

- [x] 05-02-PLAN.md — probe_delay.py (probe_and_gate + run_probe + DelayCoercedError with structured fields + ProbeResult exposing settings_sent/returned_settings) + harvest run_delay0.py → delay0_candidates.py + retire run_delay0.py

**Wave 2** *(blocked on Wave 1 completion — 05-01 imports probe_delay into hunt.py)*

- [x] 05-01-PLAN.md — `--delay` parameter threading (grade.py, researcher.py, find_alphas.py, hunt.py) + coercion warning at grade.py resolution block + `settings["delay"]`-over-`delay=` precedence + probe-skip when `--max-sims 0` + regression tests

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 05-03-PLAN.md — Empirical verification via single-process verify_delay0.py (one login, then Test A probe sim with proven settings + delay=0; Test B independent-bisection fallback if coerced); 05-VERIFICATION.md outcome record — **Test A PASS: BRAIN returned delay=0 (alpha e7rvXqwz); Test B skipped; no payload fix needed**

### Phase 6: Additivity Gate

**Goal**: A reusable additivity gate is available that ranks candidates by cheap local PnL correlation (no BRAIN call) and confirms finalists with a real BRAIN correlation check — nothing is presented as submit-ready without passing both layers
**Depends on**: Phase 4 (selfcorr primitives, grade primitives)
**Requirements**: ADD-01, ADD-02, ADD-03, ADD-04
**Success Criteria** (what must be TRUE):

  1. Given a set of candidate PnL series, `additivity.rank_by_proxy()` returns them sorted by estimated book correlation using the local PnL proxy, producing a ranked list with zero BRAIN API calls
  2. For a finalist alpha (already simulated, IS-check passing), `additivity.confirm_additive()` calls `POST /alphas/{id}/check`, reads the SELF_CORRELATION / PROD_CORRELATION results from BRAIN's `is.checks`, and returns a boolean verdict using BRAIN's own limits — no hardcoded threshold
  3. Any code path that produces a submit recommendation (hunt output, brute-force output) invokes the additivity gate and withholds the recommendation if the gate fails — a candidate cannot be labeled submit-ready by passing IS checks alone
  4. The same gate function can be called as a rank-score (returns a float) or as a yes/no filter (returns a boolean) so it is reusable in both discovery (Tool B ranking) and refinement (/iterate decorrelate mode)

**Plans**: 3 plans

Plans:
**Wave 1** *(independent)*

- [x] 06-01-PLAN.md — selfcorr.py: get_book_pnl_paths (status=ACTIVE only) + _null_stale_pnl_paths + backfill_active_pnl D-04 fix + 4 offline tests

**Wave 2** *(blocked on Wave 1)*

- [x] 06-02-PLAN.md — additivity.py: AdditivityResult dataclass + _combined_book_corr + rank_by_proxy (zero BRAIN calls) + confirm_additive (reads BRAIN live limit) + 9 offline tests

**Wave 3** *(blocked on Wave 2)*

- [x] 06-03-PLAN.md — hunt.py: _apply_additivity_gate helper + both best_submittable sites wired + 2 integration tests

### Phase 7: Brute-Force Tool (Tool B)

**Goal**: A standalone, AI-free in-repo tool (`/bruteforce`) enumerates parameterized templates, pre-filters locally, probe-sims a sample, bulk-sims survivors at ≤3 concurrent on one shared session, gates through additivity, and records only survivors plus structured failure reasons — with no second BRAIN login and no auto-submit
**Depends on**: Phase 5 (delay plumbing), Phase 6 (additivity gate)
**Requirements**: BF-01, BF-02, BF-03, BF-04, BF-05, BF-06
**Success Criteria** (what must be TRUE):

  1. User defines a template with operator/field/window slots; running `/bruteforce` enumerates all valid combinations using only verified catalog entries (zero unknown-token combinations reach simulation)
  2. Before any simulation is attempted, every enumerated combination is passed through `validate.py` and any combination with an unrecognized operator or field token is dropped and counted — the pre-filter run is observable in the log
  3. The tool probe-simulates a configurable small sample (e.g. 5 combinations) from a template; if no probe passes IS checks, the tool logs "template abandoned after probe" and skips the remaining combinations for that template without spending further simulation slots
  4. Bulk simulation of survivors runs at concurrency ≤3, reusing the existing cached BRAIN session (no new login), and stops cleanly on quota met / session expiry (401) / dry — no combinations survive to the DB without passing the additivity gate
  5. The tool runs end-to-end with the AI (LLM) completely absent from the process — it can be invoked when the Claude Code AI quota is exhausted, using only the cached BRAIN session

**Plans**: TBD

### Phase 8: Evolve /hunt + Fold /find-alphas

**Goal**: `/hunt` selects and ranks results through the additivity gate (not Sharpe alone), accepts `--delay`, and the `/find-alphas` capability is fully absorbed as `/hunt --research-only` — no separate command needed
**Depends on**: Phase 5 (delay plumbing), Phase 6 (additivity gate)
**Requirements**: CMD-01, CMD-02
**Success Criteria** (what must be TRUE):

  1. `/hunt --delay 0` threads delay-0 through the full research→grade→select pipeline; the final recommendation list contains only delay-0 alphas and each carries an additivity verdict from the gate
  2. The hunt loop's final selection ranks candidates by additivity score (local proxy first, BRAIN confirm for finalists) — a high-Sharpe but correlated alpha is ranked below a lower-Sharpe but additive one
  3. Running `/hunt --research-only` executes the Researcher + Ideator steps only (no BRAIN calls, no grading) and emits the same thesis note that `/find-alphas` produced — the `/find-alphas` command is removed or redirects to this flag

**Plans**: TBD

### Phase 9: /iterate Decorrelate Mode

**Goal**: Given an already-submittable alpha, `/iterate` can search neutralization, settings, and small mutation variants for the most-additive one that still passes all BRAIN checks — with additivity as the objective and submittability as the hard constraint
**Depends on**: Phase 6 (additivity gate)
**Requirements**: CMD-03
**Success Criteria** (what must be TRUE):

  1. Running `/iterate --decorrelate <alpha_id>` generates a set of variants (at minimum: neutralization swap, one settings variant, one small expression mutation) and grades each through the full IS-check + additivity gate
  2. The output clearly distinguishes variants that pass all checks and improve additivity, variants that pass checks but do not improve additivity, and variants that fail a check — the user can see the additivity-vs-submittability tradeoff at a glance
  3. The best variant returned is the one with the highest additivity score among those that still pass all IS checks — if no variant beats the original on additivity while staying passing, the command reports that the original is already the best available tradeoff

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. MVP Grading Engine | 5/5 | Complete | 2026-06-07 |
| 2. Grounded Generation | 4/4 | Complete | 2026-06-08 |
| 3. Smart Iteration | 6/6 | Complete | 2026-06-10 |
| 4. Optimization & Polish | 6/6 | Complete | 2026-06-11 |
| 5. Delay-0 Feasibility & Plumbing | 3/3 | Complete   | 2026-06-13 |
| 6. Additivity Gate | 3/3 | Complete   | 2026-06-15 |
| 7. Brute-Force Tool (Tool B) | 0/TBD | Not started | - |
| 8. Evolve /hunt + Fold /find-alphas | 0/TBD | Not started | - |
| 9. /iterate Decorrelate Mode | 0/TBD | Not started | - |
