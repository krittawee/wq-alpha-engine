# Grounded Alpha Discovery System

## What This Is

A self-researching WorldQuant BRAIN alpha-generation pipeline (in `~/quant`) that
reasons over a **verified knowledge base + persistent memory** to produce *decent,
genuinely-submittable* alphas — rather than guessing like existing tools. It runs as
a Claude-Code-orchestrated loop (research → ideate → grade → refine) for a BRAIN
participant who has ~16 manually-submitted alphas and wants to discover more
semi-autonomously. Improves on `popsukss/alpha-generator`.

## Core Value

Produce a **decent, genuinely-submittable alpha — verified against BRAIN's own checks
(never guessed)** — while remembering every alpha tried so the system never repeats
itself and every result adds to its diversity-aware memory.

## Current Milestone: v1.1 — Additive Alpha Discovery

**Goal:** Produce alphas that *add to the team competition score* (decorrelated from the
existing book) with verified delay-0 support — not merely alphas that pass BRAIN's checks.
**Additivity is the objective; passing the checks is the constraint** — learned when a fully
"submittable" alpha would have dropped the team d1 score by 112 (too correlated to add).

**Target features:**
- **Additivity gate** — local PnL correlation proxy + real BRAIN correlation check; nothing recommended for submit without it
- **delay-0 support** — verify BRAIN actually runs delay-0 from code (fix the send-path if coerced); thread `--delay` through the pipeline
- **Brute-force tool (Tool B)** — in-repo template enumeration (ACE template *shapes*, not its runtime), pre-filter → probe → bulk-sim → gate; runs standalone, no AI dependency
- **Evolve `/hunt`** (`--delay`, additivity-gated) and fold `/find-alphas` → `/hunt --research-only`
- **`/iterate` decorrelate mode** — improve an already-submittable alpha's additivity, constrained to stay passing

Full design: `docs/plans/2026-06-11-additive-alpha-discovery-design.md`. Two decoupled tools
share ONE BRAIN session (single-shot auth); ACE auto-submit stays OFF; submission stays manual.
Deferred: shared sim-queue for true simultaneity, and the LLM learning/memory loop.

## Requirements

### Validated

<!-- Shipped and confirmed valuable (existing working code). -->

- ✓ Biometric-aware BRAIN login — Persona handshake + 429 throttle handling (`wq_login.py`)
- ✓ End-to-end simulate → `get_alpha` → read IS stats chain (`test_sim.py`)
- ✓ v1.0 Phase 1 — MVP grading engine (sync catalog + alphas → SQLite, local validator, two-phase grade, persist)
- ✓ v1.0 Phase 2 — Grounded generation (Researcher + Ideator agents)
- ✓ v1.0 Phase 3 — Smart iteration (Editor diagnose+mutate, dedupe, self-corr pre-filter, Frequent Subtree Avoidance)
- ✓ v1.0 Phase 4 — Optimization & polish (Settings Optimizer, decay monitor, Obsidian prose layer)

### Active

<!-- Current scope — v1.1 Additive Alpha Discovery. Detailed REQ-IDs in REQUIREMENTS.md. -->

- [ ] Additivity gate (the keystone — passes-AND-adds)
- [ ] delay-0 support (verify BRAIN runs it; fix send-path; `--delay` plumbing)
- [ ] Brute-force generation tool (Tool B — in-repo, standalone, no AI dependency)
- [ ] Evolve `/hunt` (`--delay`, additivity-gated) + fold `/find-alphas`
- [ ] `/iterate` decorrelate mode (improve a submittable alpha's additivity)

### Out of Scope

- Automated submission — `POST /alphas/{id}/submit` stays **manual / human-gated** by design (avoid bad submits)
- Headless 24/7 daemon (Model B) — blocked by periodic Persona biometric; deferred until auth is solved
- Reusing the user's existing Obsidian vault — a **dedicated** KB is created instead (keeps other projects out of scope)
- Offline BRAIN simulator + RAG paper-scraping — orthogonal to a first decent alpha (local validator covers ~80%)

## Context

- Full design: `docs/plans/2026-06-07-alpha-system-design.md` (verified by a red-team agent 2026-06-07).
- Improves on `popsukss/alpha-generator`; researched against `worldquant-miner` Gen-Two, `Brainiac`, `xiegengcai/world-quant-brain`, and the "Alpha Jungle" LLM+MCTS paper (arXiv 2505.11122).
- Stack: Python 3.14 in `./venv`; `autobrain-sim` (minimal SDK: simulate/get_alpha/get_pnl/get_recordset only) + hand-written BRAIN endpoints for operators/data-fields/check/submit.
- Knowledge base = hybrid: **SQLite** (`alpha_kb.db`) for facts/alpha-history + **Obsidian** for prose ideas.
- Orchestration = **Model A** (Claude Code drives the loop; no separate API key — runs inside subscription usage).

## Constraints

- **Tech stack**: `autobrain-sim` is minimal — operators/data-fields/`POST /check`/submit are all hand-written against raw endpoints — Why: SDK lacks them.
- **Auth**: periodic Persona biometric needs a human; repeated auth → 429 BIOMETRICS_THROTTLED (15–30 min). Single-shot login, **never re-auth in-loop** — Why: lockout risk.
- **Concurrency**: BRAIN sims ~2 min each, cap concurrent sims **≤3 on one shared session** — Why: BRAIN slot cap + throttle.
- **Submittability**: read each check's `result`/`limit` from BRAIN's `is.checks`; self/prod correlation via `POST /alphas/{id}/check` — Why: BRAIN is source of truth; never hardcode 1.25/0.7.
- **SDK trap**: `simulate()` `regular` param is buggy — always use the default — Why: silently drops the expression otherwise.
- **Cost**: runs inside Claude Code subscription (Model A); BRAIN sims free but slow — Why: time, not money, is the bottleneck.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Hybrid KB (SQLite facts + Obsidian prose) | Frequent machine queries vs rarely-read human ideas | — Pending |
| Ground operators/fields from BRAIN API | Kills hallucinated-field silent failures (popsukss flaw) | — Pending |
| BRAIN is source of truth for submittability | Read `is.checks` + `POST /check`; don't guess thresholds | — Pending |
| Orchestration = Model A (Claude Code) | Biometric blocks headless; no extra API cost; stay in loop | — Pending |
| Fixed settings first, knowledge-driven optimizer later | Sims are scarce; tune only NEAR alphas | — Pending |
| Submission stays manual | Avoid auto-submitting weak/duplicate alphas | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition:**
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone:**
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-07 after initialization*
