# Requirements: Grounded Alpha Discovery System

**Defined:** 2026-06-07
**Core Value:** Produce a decent, genuinely-submittable alpha — verified against BRAIN's own checks (never guessed) — while remembering every alpha tried.

## v1 Requirements

Requirements for the initial milestone. Each maps to a roadmap phase.
Source of truth: `docs/plans/2026-06-07-alpha-system-design.md`.

### Engine (grading engine — no LLM in loop)

- [ ] **ENG-01**: System syncs BRAIN operators, data-fields, and settings options into a local SQLite catalog (`alpha_kb.db`)
- [ ] **ENG-02**: System syncs the user's existing/submitted alphas into SQLite (for self-correlation memory)
- [ ] **ENG-03**: A local validator rejects expressions whose operators/fields aren't in the catalog or whose syntax is malformed, before any simulation
- [ ] **ENG-04**: System grades an expression by simulating it and reading BRAIN's `is.checks` IS results, reading each check's `limit` rather than hardcoding thresholds
- [ ] **ENG-05**: For IS survivors, system resolves self/prod correlation via `POST /alphas/{id}/check` (poll → read from `is.checks`) and persists the values
- [ ] **ENG-06**: System persists every graded alpha plus a normalized per-check record to SQLite, deduping by expression
- [ ] **ENG-07**: System grades a hand-seeded idea list end-to-end with concurrency ≤3 on one shared authenticated session and never re-authenticates inside the loop

### Generation (grounded idea generation)

- [x] **GEN-01**: A Researcher agent produces a grounded thesis from the catalog + past results in memory
- [x] **GEN-02**: An Ideator agent generates FastExpr expressions using only verified operators/fields, tags each by archetype, and dedupes against the DB

### Iteration (smart refinement)

- [ ] **ITR-01**: An Editor classifies each alpha PASS/NEAR/FAIL from BRAIN's checks and diagnoses which check failed and why
- [ ] **ITR-02**: The Editor proposes expression mutations for the next loop, with mutation lineage recorded (`parent_alpha_id`)
- [ ] **ITR-03**: System computes a local PnL-based self-correlation pre-filter against the user's alphas to avoid duplicates cheaply
- [ ] **ITR-04**: Frequent Subtree Avoidance mines common motifs from passing alphas and steers generation toward structural novelty before simulating

### Optimization (tuning & polish)

- [ ] **OPT-01**: A knowledge-driven Settings Optimizer tunes settings for NEAR alphas by archetype (small candidate set, not a grid)
- [ ] **OPT-02**: A quality/decay monitor tracks alpha metric degradation over time using the time-stamped checks table
- [ ] **OPT-03**: An Obsidian prose layer (theses, archetype heuristics, failure notes) is maintained and linked to alpha_ids in SQLite

## v1.1 Requirements — Additive Alpha Discovery

**Milestone goal:** Produce alphas that *add to the team competition score* (decorrelated from the existing book) with verified delay-0 support — not merely alphas that pass BRAIN's checks. Additivity is the objective; passing the checks is the constraint.

### Additivity (passes-AND-adds)

- [x] **ADD-01**: System estimates a candidate's correlation to the user's existing book from a cheap local PnL proxy (no BRAIN call) so candidates can be ranked by likely additivity
- [ ] **ADD-02**: System confirms a finalist's additivity with BRAIN's real correlation check before recommending it for submission
- [ ] **ADD-03**: No alpha is presented as submit-ready unless it passes the additivity gate — passes all IS checks AND is decorrelated enough to add to the book
- [x] **ADD-04**: The additivity gate is reusable both as a yes/no filter (discovery) and as a rank-by score (refinement)

### Delay (delay-0 support)

- [x] **DLY-01**: User can request delay-0 simulations through the pipeline (`--delay 0`), threaded end-to-end (hunt and brute-force)
- [x] **DLY-02**: System verifies BRAIN's *returned* delay matches the request and surfaces any silent coercion (delay-0 run as delay-1) rather than recording the wrong value

### Brute-force generation (Tool B — standalone, no AI dependency)

- [ ] **BF-01**: User can define a parameterized template (operator/field/window slots); system enumerates the valid combinations
- [ ] **BF-02**: Every enumerated combination is locally validated against the catalog before any simulation is spent
- [ ] **BF-03**: System probe-simulates a small sample of a template and abandons the template if the sample shows no viable alpha, before bulk-simulating
- [ ] **BF-04**: System bulk-simulates surviving combinations at ≤3 concurrent on one shared session, stopping on quota met, session expiry, or dry
- [ ] **BF-05**: The brute-force tool runs standalone with no AI dependency, reusing the existing cached BRAIN session (works when the AI quota is exhausted)
- [ ] **BF-06**: System records survivors plus structured failure-reasons (not every raw combo) to the DB for future grounding

### Command evolution

- [ ] **CMD-01**: `/hunt` accepts `--delay` and selects/ranks results through the additivity gate (not Sharpe alone)
- [ ] **CMD-02**: `/find-alphas` capability is available as `/hunt --research-only` (AI-only, no BRAIN, emits the thesis note); the standalone command is retired
- [ ] **CMD-03**: `/iterate` gains a decorrelate mode — given an already-submittable alpha, it searches variants (neutralization, settings, small mutations) for the most-additive one that still passes

## v2 Requirements

Deferred beyond this milestone.

### Automation

- **AUTO-01**: Optional MCTS/genetic search to replace naive Editor mutation
- **AUTO-02**: Headless Model-B daemon (standalone `main.py` + API) once biometric auth is solved

## Out of Scope

| Feature | Reason |
|---------|--------|
| Automated submission (`POST /submit`) | Stays manual/human-gated to avoid auto-submitting weak or duplicate alphas |
| Reusing the user's existing Obsidian vault | Dedicated KB keeps unrelated projects out of scope |
| Offline BRAIN simulator | Orthogonal to a first decent alpha; local validator covers ~80% of the benefit |
| RAG paper-scraping for theses | Nice-to-have; Obsidian thesis layer covers the MVP need |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ENG-01 | Phase 1 | Pending |
| ENG-02 | Phase 1 | Pending |
| ENG-03 | Phase 1 | Pending |
| ENG-04 | Phase 1 | Pending |
| ENG-05 | Phase 1 | Pending |
| ENG-06 | Phase 1 | Pending |
| ENG-07 | Phase 1 | Pending |
| GEN-01 | Phase 2 | Complete |
| GEN-02 | Phase 2 | Complete |
| ITR-01 | Phase 3 | Pending |
| ITR-02 | Phase 3 | Pending |
| ITR-03 | Phase 3 | Pending |
| ITR-04 | Phase 3 | Pending |
| OPT-01 | Phase 4 | Pending |
| OPT-02 | Phase 4 | Pending |
| OPT-03 | Phase 4 | Pending |
| DLY-01 | Phase 5 | Complete |
| DLY-02 | Phase 5 | Complete |
| ADD-01 | Phase 6 | Complete |
| ADD-02 | Phase 6 | Pending |
| ADD-03 | Phase 6 | Pending |
| ADD-04 | Phase 6 | Complete |
| BF-01 | Phase 7 | Pending |
| BF-02 | Phase 7 | Pending |
| BF-03 | Phase 7 | Pending |
| BF-04 | Phase 7 | Pending |
| BF-05 | Phase 7 | Pending |
| BF-06 | Phase 7 | Pending |
| CMD-01 | Phase 8 | Pending |
| CMD-02 | Phase 8 | Pending |
| CMD-03 | Phase 9 | Pending |

**Coverage:**
- v1 requirements: 16 total, mapped to phases: 16
- v1.1 requirements: 15 total, mapped to phases: 15
- Unmapped: 0

---
*Requirements defined: 2026-06-07*
*Last updated: 2026-06-12 — v1.1 traceability added by roadmapper (15/15 mapped, Phases 5–9)*
