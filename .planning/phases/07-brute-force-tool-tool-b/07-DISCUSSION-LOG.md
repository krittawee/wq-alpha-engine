# Phase 7: Brute-Force Tool (Tool B) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 7-brute-force-tool-tool-b
**Areas discussed:** Template format & shapes, Probe gate criterion, Stop conditions & quota, Failure-record schema, Settings-slot scope

---

## Template format & shapes

### Q1 — How should a brute-force template be defined?

| Option | Description | Selected |
|--------|-------------|----------|
| In-repo Python module | templates.py data structures, mirrors delay0_candidates / ARCHETYPE_HEURISTICS; version-controlled, AI-free, no parser | ✓ |
| YAML/JSON config file | User-editable without touching code, but adds parser + less expressive slot logic | |
| CLI args only | Quick one-offs, unwieldy for multi-slot, not reusable | |

**User's choice:** In-repo Python module

### Q2 — Ship the 4 ACE shapes pre-loaded?

| Option | Description | Selected |
|--------|-------------|----------|
| Ship all 4 ACE shapes | sentiment, fundamental, residual, beta grounded against catalog; immediate working run | ✓ |
| Ship 1 reference shape | One worked example; user adds the rest | |
| Start empty | Pure machinery, user authors all templates | |

**User's choice:** Ship all 4 ACE shapes

### Q3 — How are field-slot values sourced?

| Option | Description | Selected |
|--------|-------------|----------|
| Catalog query, explicit fallback | Slot lists literals OR declares a catalog filter that auto-expands; validate.py backstop | ✓ |
| Explicit literal lists only | Hardcoded tokens, predictable but long and manual | |
| Catalog query only | Always filters, concise but can't pin a curated set | |

**User's choice:** Catalog query, explicit fallback

---

## Probe gate criterion

### Q1 — What counts as a probe passing?

| Option | Description | Selected |
|--------|-------------|----------|
| NEAR-or-better, no hard error | Keep if ≥1 probe sims cleanly and reaches NEAR/PASS; abandon only if all error/far-fail | ✓ |
| Full IS pass required | Strictest; high false-abandon risk for sparse templates | |
| Any clean sim (no error) | Most lenient; spends most budget on weak templates | |

**User's choice:** NEAR-or-better, no hard error

### Q2 — How is the probe sample chosen + default size?

| Option | Description | Selected |
|--------|-------------|----------|
| Spread across slot values, size 5 | Cover every slot value at least once; default 5, --probe-size configurable | ✓ |
| Random sample, size 5 | Unbiased but can miss slot values, non-reproducible | |
| First N, size 5 | Trivial but clusters on first slot values, weakest coverage | |

**User's choice:** Spread across slot values, size 5

---

## Stop conditions & quota

### Q1 — Quota unit?

| Option | Description | Selected |
|--------|-------------|----------|
| Additive survivors, default 5 | IS-pass AND gate-pass; the true objective | ✓ |
| IS-passers, default 5 | Simpler streaming, but can complete with 5 too-correlated alphas | |
| No quota — exhaust then stop | Thorough but unbounded BRAIN time | |

**User's choice:** Additive survivors, default 5

### Q2 — Default delay?

| Option | Description | Selected |
|--------|-------------|----------|
| delay-0 | Primary diversification lever; structurally decorrelated from delay-1 book | ✓ |
| delay-1 | Conventional default, larger universe, but more likely to correlate | |
| Require explicit --delay | Intentional but adds friction every run | |

**User's choice:** delay-0

### Q3 — Template ordering + 401 stop?

| Option | Description | Selected |
|--------|-------------|----------|
| Sequential per-template, checkpoint each | One template fully before next; 401 persists graded work + reports partial; never re-auth | ✓ |
| Round-robin across templates | Better early diversity if interrupted, but complex scheduling | |
| Let the planner decide ordering | Lock stop conditions, defer traversal order | |

**User's choice:** Sequential per-template, checkpoint each

---

## Failure-record schema

### Q1 — Failure-record granularity?

| Option | Description | Selected |
|--------|-------------|----------|
| Per-template aggregate + per-survivor rows | Survivors → alphas/checks; failures → per-(template,run) class counts + examples | ✓ |
| Per-combo failure rows (lightweight) | One slim row per failed sim; heavier, closer to landfill | |
| Survivors only | Cleanest DB but loses the "what didn't work" signal BF-06 wants | |

**User's choice:** Per-template aggregate + per-survivor rows

### Q2 — Storage location?

| Option | Description | Selected |
|--------|-------------|----------|
| New bruteforce_runs table + reuse runs | Survivors in alphas/checks; new table for per-template aggregates + run params | ✓ |
| Reuse runs table + JSON blob | No new table but overloads runs, awkward per-template queries | |
| Let the planner decide schema | Lock survivors+aggregates, defer table layout | |

**User's choice:** New bruteforce_runs table + reuse runs

---

## Settings-slot scope

### Q1 — Should templates enumerate settings slots too?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — settings as enumerable slots | Reuse optimizer.py to build settings grid; expr-slots × settings-slots | ✓ |
| No — expression slots only this phase | Smaller scope, defers design's "settings = more variables" | |
| Explore another area instead | — | |

**User's choice:** Yes — settings as enumerable slots

---

## Claude's Discretion

- Execution mechanics of quota-aware mid-flight stop at ≤3 concurrent (reuse `grade.grade_many` vs streaming scheduler) — planner.
- Exact `bruteforce_runs` columns/indexes, CLI flag set, and 401-detection mechanism — planner.
- Numeric "far FAIL" boundary for probe-abandon — reuse Editor `classify_from_checks`, not a new threshold.

## Deferred Ideas

- Shared sim-queue for true Tool A+B simultaneity — v1.2.
- LLM learning/memory loop over brute-force survivors + failure-reasons — v1.2 (Phase 7 only records the structured data).
- `/hunt` evolution & `/find-alphas` fold (CMD-01/02) — Phase 8.
- `/iterate` decorrelate mode (CMD-03) — Phase 9.
