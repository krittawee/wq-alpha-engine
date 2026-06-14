# Phase 5: Delay-0 Feasibility & Plumbing - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-12
**Phase:** 5-Delay-0 Feasibility & Plumbing
**Areas discussed:** Coercion response, Feasibility gate, Old script cleanup, Verification approach (why delay-0 wasn't working)

---

## Opening question — "Why can't we run delay-0 right now? Why hardcode delay=1?"

Not a multiple-choice area — a user clarifying question that reshaped the phase.
Answer given: two reasons — (1) no plumbing (commands have no `--delay`, code
hardcodes `delay=1`), and (2) feasibility was never confirmed — every past
delay-0 attempt was silently coerced to delay-1 and mislabeled. Then the user
noted **they CAN run delay-0 in the BRAIN web UI**, which proves delay-0 is
permitted for the account and means the coercion is a fixable code/payload issue
(or a delay-1-only field), not an account denial.

---

## Verification Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Capture UI request first | Grab the exact network request the UI sends; match code to it | ✓ |
| Probe + diff from code only | Trial-and-error against API docs, no browser capture | |
| I can't easily capture it | Plan around code-only probing | |

**User's choice:** Capture UI request first
**Notes:** User asked how to do the capture; given step-by-step DevTools → Network
→ `POST simulations` → "Copy as cURL" instructions, with auth headers redacted.
Capture recorded as the key required INPUT for planning; can be provided now or at
plan-phase time.

---

## Coercion response

| Option | Description | Selected |
|--------|-------------|----------|
| Warn + discard | Loud warning naming the expr/field; do not save the coerced alpha | ✓ |
| Warn + keep (labeled delay-1) | Warn but still save, stamped at its true delay | |
| Warn + abort run | Warn and stop the whole run | |

**User's choice:** Warn + discard
**Notes:** Re-asked after the UI-works reframing — coercion now expected to be
rare (most likely a delay-1-only field in one expression). Discard keeps delay-0
hunts pure and avoids re-creating the "11 mislabeled rows" problem.

---

## Feasibility gate

| Option | Description | Selected |
|--------|-------------|----------|
| Probe-gate + per-sim guard | One probe sim before the full run; abort if delay-1; warn+discard during run | ✓ |
| Per-sim guard only | No upfront probe; rely on warn+discard each sim | |
| Probe is the whole phase | Standalone manual check command, no auto-gating | |

**User's choice:** Probe-gate + per-sim guard
**Notes:** Protects slow ~2-min sim slots — fail fast if delay-0 is fully broken,
catch stray bad-field coercions per sim.

---

## Old script cleanup

| Option | Description | Selected |
|--------|-------------|----------|
| Harvest then retire | Pull useful knowledge (confirmed delay-0 field list, patterns) into clean pipeline, then delete/archive `run_delay0.py` | ✓ |
| Leave it untouched | Build new path alongside; defer old script | |
| Delete outright | Remove now, discard its notes | |

**User's choice:** Harvest then retire
**Notes:** Field list is unverified (coexisted with the mislabeling bug) — harvest
it as a hypothesis to re-confirm via the probe, not as ground truth. Goal: one
delay-0 path, no drift.

---

## Claude's Discretion

- **Default delay:** User did not elect to discuss; locked the sensible default —
  delay-1 stays the default when `--delay` is omitted, delay-0 is explicit opt-in.
- **Warning loudness/location** and **probe-verdict caching** — left to planner's
  judgment (use conventional, visible choices).

## Deferred Ideas

None — discussion stayed within phase scope. Delay-0 *usage* in hunt selection /
bruteforce / additivity is already scoped to Phases 6–8, not deferred here.
