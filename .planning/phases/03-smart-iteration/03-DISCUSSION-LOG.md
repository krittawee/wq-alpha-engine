# Phase 3: Smart Iteration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-09
**Phase:** 03-smart-iteration
**Areas discussed:** Editor brain, NEAR vs FAIL line, Local self-corr data, FSA wiring, Autonomous loop control, PnL download mechanics, Entry point / command

---

## Editor brain (architecture)

| Option | Description | Selected |
|--------|-------------|----------|
| Hybrid | Code classifies + pinpoints broken check; LLM writes diagnosis + proposes mutations | ✓ |
| Pure rule-based | All code, templated diagnosis, mutations from existing variant functions | |
| Pure LLM Editor | LLM does classify/explain/mutate end-to-end | |

**User's choice:** Hybrid
**Notes:** User asked for a simple explanation of each area before deciding. Hybrid mirrors the Phase 2 Researcher pattern (deterministic + bounded LLM).

## Editor brain (mutation volume)

| Option | Description | Selected |
|--------|-------------|----------|
| 1–3 per NEAR & FAIL | Mutate both, 1–3 each, NEAR priority | ✓ |
| Only NEAR, 2–4 each | Skip FAILs (deviates from roadmap criterion 2) | |
| 1–3, count scales by status | NEAR 2–3, FAIL 1 | |

**User's choice:** 1–3 per NEAR & FAIL

## Editor brain (mutation safety)

| Option | Description | Selected |
|--------|-------------|----------|
| Validate, drop invalid | validate.py + expr_exists gate; drop invalid/dupes | ✓ |
| Validate + auto-repair | One LLM retry on validation failure | |
| Constrained to known ops | LLM limited to existing variant vocabulary | |

**User's choice:** Validate, drop invalid

## Editor brain (handoff)

| Option | Description | Selected |
|--------|-------------|----------|
| Stop for human review | Persist + emit seeds file, human grades via cli.py | |
| Auto-queue & grade | Editor feeds mutations into grade_many autonomously | ✓ |
| Persist only, no emit | Write to DB, undefined pickup | |

**User's choice:** Auto-queue & grade
**Notes:** Deliberate divergence from Phase 2's human-in-the-loop. Captured constraint: must respect ≤3 concurrent sims + single-shot auth (never re-auth in-loop).

---

## NEAR vs FAIL (margin)

| Option | Description | Selected |
|--------|-------------|----------|
| Within 20% of limit | Single tunable margin | ✓ |
| Within 10% (strict) | Tighter band | |
| Per-check margins | Different margin per check type | |

**User's choice:** Within 20% of limit

## NEAR vs FAIL (hard checks)

| Option | Description | Selected |
|--------|-------------|----------|
| Any hard fail → FAIL | Structural/boolean fail forces FAIL | ✓ |
| Hard fails ignored for NEAR | Judge NEAR on numeric only | |
| Editor (LLM) decides | LLM judges salvageability | |

**User's choice:** Any hard fail → FAIL

## NEAR vs FAIL (fail count)

| Option | Description | Selected |
|--------|-------------|----------|
| At most 2 | ≤2 failing numeric checks, all within margin | ✓ |
| Exactly 1 | Single check missed | |
| Any count, all within margin | No cap | |

**User's choice:** At most 2
**Notes:** User asked for a recommendation + explanation. Recommended "at most 2" because numeric checks are few and correlated (Sharpe+fitness often miss together); catches the realistic salvage case while rejecting broadly-weak alphas.

---

## Local self-corr (filter timing)

| Option | Description | Selected |
|--------|-------------|----------|
| Post-sim, pre-BRAIN-check | Compare locally before POST /check | |
| Parent-PnL proxy, pre-sim | Use parent's PnL as proxy before simulating | |
| Both (proxy gate + post-sim) | Cheap pre-sim gate + precise post-sim filter | ✓ |

**User's choice:** Both
**Notes:** Surfaced the core tension — PnL only exists after simulation, so a fully pre-sim PnL filter for fresh candidates is impossible; reference alphas can be cached, candidates use parent proxy pre-sim + precise filter post-sim.

## Local self-corr (reference set)

| Option | Description | Selected |
|--------|-------------|----------|
| Submitted + passing DB alphas | Mirrors BRAIN + stops self-rediscovery | ✓ |
| Submitted only | Smallest, mirrors BRAIN exactly | |
| All PnL we have | Widest, includes FAILs | |

**User's choice:** Submitted + passing (recommended)
**Notes:** User asked for a recommendation. Recommended submitted + passing because the autonomous loop (chosen above) would otherwise rediscover its own winners; FAILs excluded as irrelevant to resemble.

## Local self-corr (method)

| Option | Description | Selected |
|--------|-------------|----------|
| Pearson on daily PnL + calibrate + research-confirm | BRAIN's documented method, validated against stored self_corr | ✓ |
| Pearson, skip calibration | Just Pearson, no validation | |

**User's choice:** Lock the bundle
**Notes:** User asked whether BRAIN's method can be searched/reverse-engineered. Answer: BRAIN docs document max-Pearson-on-daily-PnL; also calibrate locally against stored `self_corr` values. Researcher to confirm exact definition + PnL endpoint/date-window.

## Local self-corr (cutoff)

| Option | Description | Selected |
|--------|-------------|----------|
| Derive from BRAIN limit | Read SELF_CORRELATION limit from checks table | ✓ |
| Fixed 0.7 | Hardcoded (violates CLAUDE.md) | |
| Aggressive fixed 0.5 | Aggressive hardcode | |

**User's choice:** Derive from BRAIN limit

---

## FSA wiring (motif mining)

| Option | Description | Selected |
|--------|-------------|----------|
| AST subtree mining | Parse FastExpr to tree, count abstracted subtrees | ✓ |
| Operator n-grams | Operator sequences, no parser | |
| Operator frequency only | Tally dominant operators | |

**User's choice:** AST subtree mining (recommended)
**Notes:** User asked for a deep explanation of FSA (provided with concrete tree examples) and a recommendation. Recommended AST because it is the only genuinely structural option and the only one that yields the diversity metric the success criterion requires; FastExpr parser is small and reused for mutation validation.

## FSA wiring (hook)

| Option | Description | Selected |
|--------|-------------|----------|
| Filter + LLM steer (both) | Post-gen filter on Ideator + avoid-list into Researcher/Editor prompts | ✓ |
| Post-gen filter only | Filter Ideator output only | |
| LLM steer only | Inject avoid-list into prompts only | |

**User's choice:** Filter + LLM steer (recommended)
**Notes:** Filter is the must-have hard guarantee on the deterministic Ideator; LLM steer is the cheap high-value bonus. Reinterprets roadmap's "Ideator's prompt" since the Ideator has no prompt.

---

## Autonomous loop control (stop rule)

| Option | Description | Selected |
|--------|-------------|----------|
| Depth + budget + dry | Stop on max depth OR sim budget OR no new NEAR | ✓ |
| Max generations only | Fixed depth only | |
| Sim budget only | Fixed sim count only | |

**User's choice:** Depth + budget + dry (recommended)

## Autonomous loop control (limits)

| Option | Description | Selected |
|--------|-------------|----------|
| 2 gens, ~30 sims/run | Conservative default (~20 min wall) | ✓ |
| 3 gens, ~50 sims/run | Deeper exploration (~35 min) | |
| 1 gen, ~15 sims/run | Most conservative single pass | |

**User's choice:** 2 gens, ~30 sims/run

---

## PnL download mechanics (fetch/cache)

| Option | Description | Selected |
|--------|-------------|----------|
| Backfill submitted + lazy passers | One-time submitted backfill + lazy-cache passers | ✓ |
| Pure lazy on demand | Fetch on first need | |
| Full upfront backfill | Download entire reference set up front | |

**User's choice:** Backfill submitted + lazy passers (recommended)

## PnL download mechanics (fallback)

| Option | Description | Selected |
|--------|-------------|----------|
| Skip local, fall back to BRAIN | Local filter is optimization, BRAIN /check is truth | ✓ |
| Treat as non-duplicate | Assume distinct on missing PnL | |
| Block / retry until available | Don't proceed without PnL | |

**User's choice:** Skip local, fall back to BRAIN (recommended)

---

## Entry point / command (Editor entry)

| Option | Description | Selected |
|--------|-------------|----------|
| New /iterate command | Claude command mirroring /find-alphas | ✓ |
| Extend cli.py grading | Grade + iterate in one shot | |
| New cli.py subcommand | python cli.py iterate | |

**User's choice:** New /iterate command (recommended)

## Entry point / command (integration)

| Option | Description | Selected |
|--------|-------------|----------|
| Filter in grade path, FSA in generation | Each filter where its trigger already is | ✓ |
| All in the new /iterate command | Centralize self-corr + FSA | |
| New standalone modules, wired by caller | Independent modules imported by entry points | |

**User's choice:** Filter in grade path, FSA in generation (recommended)
**Notes:** Module structure (editor.py / selfcorr.py / fsa.py as standalone files) left to Claude's discretion; this decision is about where each is triggered.

---

## End-to-end auto-run (correction round, post-CONTEXT)

User clarified their core vision after initial CONTEXT.md: they want ONE command
that researches → generates → simulates → iterates → keeps simulating until a new
high-performing alpha emerges — not three separate steps.

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — one chained command | /hunt: generate→grade→mutate-loop in one shot, bounded, hands-off | ✓ |
| Keep 3 separate steps | /find-alphas → cli.py → /iterate | |
| Chained, but human confirms before grading | One pause before spending sims | |

**User's choice:** Yes — one chained command (`/hunt`)

| Option | Description | Selected |
|--------|-------------|----------|
| First new submittable PASS | Stop at first new fully-passing alpha | |
| Beat my current best | Iterate until it beats existing book on a metric | |
| Run budget, return the best | Use full budget, return best new submittable alpha | ✓ |

**User's choice:** Run budget, return the best

**Honest constraint surfaced & accepted:** cannot loop literally forever — single-shot
auth (never re-auth in-loop) + ≤3-sim throttle (CLAUDE.md) force a configurable budget
ceiling. The loop runs to budget and stops cleanly; the ceiling is user-tunable so it
practically "keeps going" within an auth session. → D-16, D-17, D-18, D-20.

## Claude's Discretion

- FSA "frequent" threshold + cold-start min-sample guard
- PnL caching mechanics (storage format, vector alignment, date-window pending research)
- Internal module structure and LLM prompt wording
- FastExpr parser implementation details

## Deferred Ideas

- Settings Optimizer, decay monitor, Obsidian prose/Archetypes layer → Phase 4 (OPT-01..03)
- Richer FSA (cross-archetype motif analysis, weighted novelty scoring) → future enhancement
