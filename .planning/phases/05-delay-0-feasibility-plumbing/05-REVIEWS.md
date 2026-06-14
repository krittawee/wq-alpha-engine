---
phase: 5
reviewers: [codex]
reviewed_at: 2026-06-12T16:23:32Z
plans_reviewed: [05-01-PLAN.md, 05-02-PLAN.md, 05-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 5

> **Reviewer availability note:** Of the external AI CLIs configured for `/gsd-review`,
> only **Codex** (GPT, `codex-cli 0.139.0`) was reachable. Cursor was unauthenticated,
> and Gemini/OpenCode/Qwen/CodeRabbit were not installed. Claude is skipped by design
> (it is the host CLI and cannot serve as an independent reviewer). This review therefore
> reflects a **single independent perspective** — treat the "Consensus Summary" below as
> Codex's synthesis, not a multi-model agreement.

## Codex Review

## 05-01-PLAN.md

**Summary** — Strong implementation plan for the core plumbing and the most important safety behavior: requested-vs-returned delay comparison with warn-and-discard. The plan is concrete and testable, but it has a few ordering and integration risks around `probe_delay`, `settings=` callers, and how `hunt --delay 0 --max-sims 0` behaves.

**Strengths**
- Correctly treats BRAIN's returned settings as source of truth.
- Explicitly prevents the previous failure mode: coerced delay-1 alphas being persisted as delay-0.
- Keeps delay-1 as default, making delay-0 explicit opt-in.
- Good regression coverage for coerced and non-coerced cases.
- Avoids mutating `_BASE_SETTINGS`, which is important for safe repeated runs.

**Concerns**
- **MEDIUM:** Plan metadata says `wave: 2` and `depends_on: [05-02]`, while the roadmap says 05-01 and 05-02 are Wave 1 independent. The dependency is justified only because `hunt.py` imports `probe_delay`; consider splitting grade/threading from probe wiring if parallelism matters.
- **MEDIUM:** `settings is not None` makes `delay=` ignored. That is backward-compatible, but it can surprise callers. The plan should require warning or documentation that explicit `settings["delay"]` wins over the `delay` argument.
- **MEDIUM:** `int(resolved_delay)` may fail if BRAIN omits delay or returns `None`. The plan says fallback exists, but the comparison instruction should normalize defensively.
- **MEDIUM:** `hunt --delay 0 --max-sims 0` may still fire `probe_and_gate`, burning a live sim despite a zero-sim invocation. The success criteria include this command, so the plan should define whether probe is skipped when no simulations will run.
- **LOW:** Returning `{"status": "coerced"}` from `grade_one` may require `grade_many` and downstream reporting to explicitly handle that status.
- **LOW:** `find_alphas.py` gets a function parameter but no CLI/command parameter. That may be fine for Phase 5, but should be intentional.

**Suggestions**
- Add precedence rule: `settings["delay"]` overrides `delay`; maybe assert or warn if both are supplied and differ.
- Normalize delay comparison with a helper, e.g. fallback before casting and handle missing/non-int values clearly.
- Probe only when `delay != 1` and the hunt will actually run at least one simulation.
- Add a test that `grade_many(..., delay=0)` forwards to `grade_one`.
- Add a test or grep check that no root hardcoded `delay=1` remains except defaults.

**Risk Assessment: MEDIUM** — The core design is sound, but the probe integration and live-sim behavior need tightening to avoid accidental sim-slot waste or unclear caller precedence.

---

## 05-02-PLAN.md

**Summary** — Good small plan for isolating the delay-0 probe and retiring the old script. It correctly reuses the existing simulation path and avoids auth inside the probe. Main concerns are around the probe settings being too rigid, `conn` being unused, and the archival operation conflicting with the current read-only execution environment if actually run here.

**Strengths**
- Cleanly separates probe-gate behavior into `probe_delay.py`.
- Uses `grade._simulate_to_alpha()` instead of duplicating simulation/retry logic.
- Preserves useful `run_delay0.py` knowledge while marking it unverified.
- Correctly avoids re-authentication and lets 401 propagate.
- Explicitly avoids copying the old `_BASE_SETTINGS` mutation pattern.

**Concerns**
- **MEDIUM:** `probe_and_gate(client, conn, ...)` receives `conn` but does not use it. That creates API noise and may confuse future callers.
- **MEDIUM:** The probe uses `_BASE_SETTINGS` with only delay flipped. That is correct for Test A, but if Test A fails and Test B identifies a safer settings shape, the plan does not clearly say how `probe_delay.py` should be updated afterward.
- **MEDIUM:** Moving `run_delay0.py` with `git mv` is appropriate in a writable repo, but this session's filesystem is read-only. Execution would be blocked unless permissions change.
- **LOW:** `PROBE_EXPRESSION = "rank(vwap)"` is reasonable, but "always-valid" is too strong. It depends on region/universe/operator catalog availability.
- **LOW:** Importing a private function `_simulate_to_alpha` is acceptable for this internal tool, but should be documented as an intentional coupling.

**Suggestions**
- Either remove `conn` from `probe_and_gate` or document it as reserved for future DB/probe recording.
- Add optional `settings_override` or a second helper for UI-verbatim settings so Test B does not need to bypass the probe module.
- Make `DelayCoercedError` include `requested_delay`, `returned_delay`, and `alpha_id` fields, not only a message.
- Replace "confirmed delay-0 field" wording with "claimed delay-0 field" everywhere in `delay0_candidates.py`.
- Add a unit test with mocked `_simulate_to_alpha` for pass and coerced probe outcomes.

**Risk Assessment: LOW-MEDIUM** — The module is simple and well-scoped. Risk mainly comes from hardcoded assumptions and unclear post-Test-B evolution.

---

## 05-03-PLAN.md

**Summary** — This plan captures the necessary empirical verification step, but it is the weakest of the three because it assumes persistence of a live `client` object across human checkpoints and contains some mismatches with the implemented probe behavior. The verification concept is right; the execution protocol needs to be made more operationally realistic.

**Strengths**
- Correctly distinguishes Test A minimal-change verification from Test B UI-verbatim fallback.
- Documents full sent and returned settings, which is exactly what this phase needs.
- Includes human gates for biometric auth and final acceptance.
- Bounds the bisection work, limiting sim-slot burn.
- Treats BRAIN's response as authoritative.

**Concerns**
- **HIGH:** "Keep the returned `client` object" across a human checkpoint is not practical unless the same Python process remains alive. A `client` object cannot be resumed just because the user types "authenticated."
- **HIGH:** Task 1 says use `probe_and_gate()` but also "directly inspect alpha['settings'] from the underlying `_simulate_to_alpha` call." The current `probe_and_gate()` returns only `ProbeResult`, not the full returned settings. Either the probe result must include returned settings, or Task 1 must call `_simulate_to_alpha` directly.
- **MEDIUM:** The plan says "If Test B PASS… identify which key causes coercion," but only tests adding keys in a limited order. Multiple interacting settings could be involved.
- **MEDIUM:** Threat model says probe sims may persist to DB, but `probe_delay.py` uses `_simulate_to_alpha()` only, so it should not persist. That threat entry is inaccurate.
- **MEDIUM:** "COERCION WARNING was printed during the probe sim" is not true if coercion is detected by `probe_and_gate`, which raises `DelayCoercedError` with a `[probe_delay]` stderr line, not grade.py's `COERCION WARNING`.
- **LOW:** Test B settings comment says "14 keys minus maxTrade," but the UI payload has 13 settings keys. Clean this up to avoid executor confusion.
- **LOW:** `python hunt.py --delay 0 --max-sims 0` may trigger a probe depending on 05-01 implementation, which would make this a live API check disguised as an argparse smoke test.

**Suggestions**
- Replace the "keep client object" checkpoint with a single script command that logs in once and runs Test A/Test B in the same Python process.
- Add `returned_settings` and maybe `settings_sent` to `ProbeResult`, or create `probe_delay.run_probe()` that returns full diagnostic data without throwing.
- Make Test B use a helper in `probe_delay.py`, not ad hoc `_simulate_to_alpha`, so the verified path is the path future code uses.
- Fix verification wording: probe coercion should require `DelayCoercedError` or `[probe_delay]` output; grade coercion warning is covered by unit tests.
- Record whether probe alphas are persisted. If using `_simulate_to_alpha`, they are not persisted by grade.py.
- Make bisection explicit: test each diff independently from the UI baseline, then optionally test combinations if needed.

**Risk Assessment: MEDIUM-HIGH** — The empirical goal is correct, but live-session handling and mismatch between `probe_and_gate()` output and required verification data could cause execution failure or incomplete evidence.

---

## Overall Assessment

The plan set is directionally solid and should achieve Phase 5 after revisions. The strongest parts are the core safety invariant: requested delay must match BRAIN-returned delay, and coerced delay-0 results must not be persisted. The main risks are operational rather than conceptual: live auth/session handling, probe behavior when no sims are requested, and inconsistent assumptions about what `probe_and_gate()` returns.

I would revise 05-03 before execution, and lightly patch 05-01/05-02 to clarify delay precedence, skip probes for zero-sim dry runs, and expose full probe diagnostics. Overall risk: **MEDIUM** after those fixes; **MEDIUM-HIGH** if executed exactly as written.

---

## Consensus Summary

Only one independent reviewer (Codex) was reachable, so the items below are Codex's
prioritized findings rather than cross-model consensus. They are ordered by the leverage
they have on whether Phase 5 succeeds on first execution.

### Agreed Strengths
- The core safety invariant — compare BRAIN's **returned** delay against the **requested**
  delay, warn, and **discard** rather than persist coerced delay-0 alphas — is the right
  design and directly fixes the prior delay-recording mismatch.
- Reusing `grade._simulate_to_alpha()` for the probe (instead of duplicating sim/retry
  logic) and never re-authenticating inside the probe are both correct and low-risk.
- Delay-1 stays the default; delay-0 is explicit opt-in.

### Agreed Concerns (highest priority first)
1. **[HIGH — 05-03] Live `client` object cannot survive a human auth checkpoint.** The
   verification protocol assumes a Python object persists across a "type 'authenticated'"
   gate. Rework as a single script that logs in once and runs Test A + Test B in the same
   process.
2. **[HIGH — 05-03] `probe_and_gate()` output doesn't expose what verification needs.** It
   returns only `ProbeResult`, but Task 1 needs the full returned `settings`. Add
   `returned_settings`/`settings_sent` to the result (or a non-throwing `run_probe()`),
   so the verified path is the path future code actually uses.
3. **[MEDIUM — 05-01/05-03] Zero-sim dry run may still burn a live sim.**
   `hunt --delay 0 --max-sims 0` (a success-criteria command) could still fire the probe.
   Decide and document: probe only when `delay != 1` **and** at least one sim will run.
4. **[MEDIUM — 05-01] `delay=` vs `settings["delay"]` precedence is silent.** When
   `settings` is passed, the `delay` arg is ignored. Add an explicit precedence rule and
   warn if both are supplied and differ.
5. **[MEDIUM — 05-03] Threat-model / wording mismatches.** Probe uses `_simulate_to_alpha`
   (does **not** persist), yet the threat model says probe sims may hit the DB; and
   coercion surfaces as `DelayCoercedError` / `[probe_delay]`, not grade.py's
   `COERCION WARNING`. Fix the docs so executors verify the right signal. Also: Test B
   says "14 keys minus maxTrade" but the UI payload has 13 keys.
6. **[LOW–MEDIUM — 05-01/05-02] Defensive normalization + dead param.** `int(resolved_delay)`
   should normalize missing/`None`; `probe_and_gate(client, conn, …)` takes an unused
   `conn`; enrich `DelayCoercedError` with `requested/returned/alpha_id` fields.

### Divergent Views
None — single reviewer this round. The two HIGH items in 05-03 are the strongest signal
that **05-03 should be revised before execution**, while 05-01 and 05-02 need only light
patches.
