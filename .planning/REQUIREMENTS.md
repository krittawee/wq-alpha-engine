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

**Coverage:**
- v1 requirements: 16 total
- Mapped to phases: 16
- Unmapped: 0

---
*Requirements defined: 2026-06-07*
*Last updated: 2026-06-07 — traceability confirmed by roadmapper (16/16)*
