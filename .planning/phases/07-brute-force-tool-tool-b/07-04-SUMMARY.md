---
phase: 07-brute-force-tool-tool-b
plan: "04"
subsystem: bruteforce-command
tags: [command-file, static-test, ai-free, wq-brain]
dependency_graph:
  requires: [07-03]
  provides: [/bruteforce-command, BF-05-static-test]
  affects: [.claude/commands/bruteforce.md, test_phase7.py]
tech_stack:
  added: []
  patterns: [hunt.md-command-pattern, single-shot-auth, argparse-cli]
key_files:
  created:
    - .claude/commands/bruteforce.md
  modified:
    - test_phase7.py
decisions:
  - "bruteforce.md mirrors hunt.md structure exactly: title, auth callout, 4-step agent protocol, stop conditions, flags table, auth/concurrency constraints, module references, output"
  - "test_no_llm_imports checks both bruteforce.py and templates.py for claude/anthropic/llm/openai terms (case-insensitive) — covers both engine files as required by BF-05"
  - "Human-verify checkpoint (Task 2) deferred — requires live BRAIN session with biometric auth; cannot run in subagent"
metrics:
  duration: "~8 minutes"
  completed: "2026-06-16"
  tasks_total: 2
  tasks_completed: 1
  tasks_deferred: 1
---

# Phase 7 Plan 04: /bruteforce Command File + BF-05 Static Test Summary

**One-liner:** /bruteforce command file wiring bruteforce.bruteforce() to Claude Code via hunt.md pattern, plus AI-free static check test.

## What Was Built

**Task 1 (completed — commit 752467f):**

- `.claude/commands/bruteforce.md` — new command file for the `/bruteforce` command. Mirrors `hunt.md` structure with:
  - Bold auth callout at top (wq_login ONCE, 429 BIOMETRICS_THROTTLED lockout warning)
  - 4 numbered agent steps: single-shot auth, run bruteforce.bruteforce(), handle 401 (try/except HTTPError), display results
  - Stop conditions section (quota_met / 401 / dry)
  - Flags table (--db, --delay, --quota, --probe-size, --templates)
  - Auth constraint section (non-negotiable, from CLAUDE.md)
  - Concurrency constraint section (ThreadPoolExecutor max_workers=3)
  - Module references for all 11 files bruteforce.py imports
  - Output section (quota_count, additive_ids, DB rows, failure summary)

- `test_phase7.py` — appended `test_no_llm_imports` (BF-05 static check):
  - Opens bruteforce.py and templates.py as raw text
  - Asserts none of 'claude', 'anthropic', 'llm', 'openai' appear (case-insensitive)
  - Confirms Tool B is AI-free without requiring a live BRAIN session

**All 11 tests in test_phase7.py pass.**

## Task 2: DEFERRED (human-verify checkpoint)

Task 2 is a `checkpoint:human-verify` with `gate="blocking"`. It requires:
- A live BRAIN session (biometric Persona auth if session is stale)
- Running real simulations against BRAIN

This cannot be automated in a subagent. The orchestrator/user must perform this verification.

### 5 ROADMAP Success Criteria Awaiting Live Confirmation

| SC | Criterion | Verification Command |
|----|-----------|---------------------|
| SC-1 | Template enumeration uses only verified catalog entries (zero unknown-token combos reach sim) | Run /bruteforce with template_names=["beta_neutral"]; observe n_combos vs n_validated counts in log |
| SC-2 | Pre-filter run observable in log (dropped count + dropped reason per template) | Same run; observe "validate_dropped" count in output |
| SC-3 | Probe sim; "template abandoned after probe" logged if probe fails; remaining combos skipped | Run /bruteforce --probe-size 5 on residual_momentum; observe probe abandon log message if all probes fail |
| SC-4 | Bulk sim at ≤3 concurrent on cached session; stops on quota/401/dry; additivity gate required | Run /bruteforce --quota 1 with single template; observe ≤3 concurrent log; confirm stop_reason in output |
| SC-5 | Tool runs end-to-end with AI completely absent (no LLM call during the run) | test_no_llm_imports passes (automated, already verified); observe no LLM call during live run |

### How to Verify (complete instructions from 07-04-PLAN.md Task 2)

```bash
# Check 1 — Full unit test suite (no BRAIN session needed):
python -m pytest test_phase7.py -v
# Expected: 11 tests, all pass.

# Check 2 — Dry run (no sims, no BRAIN session needed):
python bruteforce.py --quota 1 --probe-size 1 --templates residual_momentum
# Expected: Enumerate combos, validate, skip sims, stop_reason = "dry"

# Checks 3-5 require a live BRAIN session (run wq_login.login() once interactively first):

# Check 3 — SC-1 + SC-2:
# Run /bruteforce with template_names=["beta_neutral"]
# Observe: n_combos, n_validated, validate_dropped in log

# Check 4 — SC-3 (probe abort):
# Run /bruteforce --probe-size 5 on residual_momentum
# Either probe survives or "template abandoned after probe" message appears

# Check 5 — SC-4 + SC-5:
# Run /bruteforce --quota 1 with single template
# Observe: ≤3 concurrent sims, no LLM call, stop_reason printed
```

Signal approval: type "approved" in the session after all checks pass.

## Deviations from Plan

None for Task 1 — plan executed exactly as written.

The Task 2 deferral is intentional per orchestrator instructions: human-verify checkpoint requires live BRAIN session with biometric auth and cannot run in a subagent.

## Verification Results (Automated)

```
python -m pytest test_phase7.py -x -q
...........
11 passed in 0.12s

ls -la .claude/commands/bruteforce.md
.rw-r--r-- 7.2k winter.__.kor 16 Jun 10:06 .claude/commands/bruteforce.md

grep -c "login()" .claude/commands/bruteforce.md  → 4
grep -c "ONCE" .claude/commands/bruteforce.md     → 3
grep -c "ThreadPoolExecutor" .claude/commands/bruteforce.md → 1
```

## Self-Check: PASSED

- .claude/commands/bruteforce.md: FOUND
- test_phase7.py (11 tests): PASSED
- Commit 752467f: FOUND
- No unexpected file deletions
