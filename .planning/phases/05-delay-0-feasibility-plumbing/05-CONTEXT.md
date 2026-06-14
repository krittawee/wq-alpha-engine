# Phase 5: Delay-0 Feasibility & Plumbing - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Confirm that BRAIN actually runs delay-0 simulations when requested from code
(rather than silently coercing them to delay-1), wire coercion detection +
visible warnings into the grading path, and thread a `--delay` parameter
end-to-end from the CLI to the simulate call.

**Reframed by discussion:** The user CAN run delay-0 in the BRAIN web UI, which
proves delay-0 is permitted for this account. Therefore the past silent
downgrades were almost certainly a **code/payload defect** (our hand-built
request doesn't match what the UI sends) or a **delay-1-only data field**, NOT
an account-level denial. The phase is consequently a *plumbing + verification*
job: match the UI's request, prove BRAIN returns `delay=0`, and surface any
remaining coercion loudly — not "obtain permission for delay-0."

Maps to requirements **DLY-01** (request delay-0 end-to-end) and **DLY-02**
(verify BRAIN's returned delay matches the request; surface silent coercion).

**Already done — do NOT re-plan:** The "DB records the *requested* delay instead
of BRAIN's *actual* returned delay" bug was fixed on 2026-06-11
(`grade.py:193` resolves each settings field from BRAIN's response with
`active_settings` as fallback; the 11 stale rows were corrected; regression test
`test_grade_records_brain_actual_settings` exists). Remaining DLY-02 work is the
*visible coercion warning* + requested-vs-returned comparison, NOT the recording
itself.
</domain>

<decisions>
## Implementation Decisions

### Verification Approach (how we prove delay-0 works)
- **D-01 (REVISED 2026-06-12 after capturing BOTH UI payloads):** The UI's
  delay-0 and delay-1 requests are identical except the `delay` integer, so the
  method is simply "flip the delay number." Verify with a minimal-change
  experiment, ordered:
  - **Test A (minimal change):** take our PROVEN working delay-1 `_BASE_SETTINGS`,
    set `delay=0`, run one sim, read BRAIN's returned `delay`. If it returns
    `delay=0` → the main code path was never broken (old coercion came from the
    ad-hoc `run_delay0.py`, not here). Thread `--delay` and proceed.
  - **Test B (guaranteed-good fallback):** if A is coerced to delay-1, use the
    user's CAPTURED UI delay-0 settings object verbatim (known to return a real
    delay-0). Then optionally bisect the 3 diffs (`maxTrade`/`decay`/`testPeriod`)
    to identify which key trips coercion at delay-0.
  This is more scientific than "blindly mirror the UI" (the user's suggestion):
  change one variable, keep our proven values, and only fall back to the UI
  object if needed. Both UI payloads are recorded in `<specifics>`.
- **D-02:** **The captured UI request is the key required INPUT for planning —
  NOW OBTAINED (2026-06-12).** Full payload + diff vs our code in `<specifics>`.
  Headline: `delay:0` placement already matches; the prime suspect for coercion
  is our extra `maxTrade:"ON"` key (UI omits it). The phase must build delay-0
  settings that mirror the captured UI payload exactly and verify BRAIN returns
  `delay=0`. Secondary hypothesis to test: the SDK's buggy `simulate()` may be
  ignoring our `settings=` arg entirely (cf. the `regular`-param trap in
  CLAUDE.md) — confirm our settings actually reach BRAIN.

### Coercion Response (BRAIN returns delay-1 despite a delay-0 request)
- **D-03:** **Warn + discard.** When a delay-0 run produces an alpha that BRAIN
  actually ran at delay-1, print a loud warning that names the offending
  expression/field, and **do not persist that alpha to the DB.** Rationale: a
  delay-1 result is not what a delay-0 hunt asked for; saving it re-creates the
  "11 mislabeled rows" mess. After matching the UI request, coercion is expected
  to be *rare* — most likely caused by an expression using a delay-1-only field.

### Feasibility Gate (protect slow ~2-min sim slots)
- **D-04:** **Probe-gate + per-sim guard.** Before any delay-0 hunt/bruteforce,
  fire ONE probe simulation; read back BRAIN's returned delay. If `delay=0` →
  proceed with the full run. If `delay=1` → stop immediately and report
  "delay-0 isn't working right now" plus what BRAIN returned (fail fast, don't
  burn dozens of slots). During the run, the D-03 warn+discard rule handles
  stray coerced alphas. Upfront probe = catches "fully broken"; per-sim guard =
  catches single bad fields.

### Old Script Cleanup
- **D-05:** **Harvest then retire `run_delay0.py`.** Extract its useful
  knowledge into the clean pipeline — especially its hardcoded "confirmed
  delay-0 fields" list (`volume, vwap, nws12_afterhsz_sl, open, close, ...`) and
  any candidate patterns worth keeping — then delete/archive the script so there
  is ONE delay-0 code path with no drift. CAVEAT for the planner: that field
  list is *unverified* (it coexisted with the mislabeling bug), so treat it as a
  hypothesis to re-confirm via the probe, not as ground truth.

### Claude's Discretion
- **Default delay:** User did not elect to discuss this, so the sensible default
  is locked: **delay-1 remains the default when `--delay` is omitted; delay-0 is
  explicit opt-in via `--delay 0`.** All current code hardcodes `delay=1`
  (`grade.py:48`, `find_alphas.py:71`, `researcher.py`), so threading `--delay`
  means replacing those hardcodes with a parameter that *defaults* to 1.
- **Warning surface (loudness/location)** and **whether the probe verdict is
  cached** were raised as possible follow-ups but left to the planner's
  judgment — pick conventional, visible choices (stderr/log warning; re-probe
  per run unless caching is trivially safe).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` § "Phase 5: Delay-0 Feasibility & Plumbing" — goal + 3 success criteria
- `.planning/REQUIREMENTS.md` § DLY-01, DLY-02 — the two requirements this phase satisfies

### Project constraints (must honor)
- `CLAUDE.md` § Constraints — concurrency ≤3 on one shared session; never re-auth
  in-loop; `simulate()` `regular`-param trap (BRAIN silently drops malformed input
  — the same reason delay-0 was being ignored); read check limits from BRAIN,
  never hardcode.

### Existing code touched by this phase
- `grade.py:48` — `DEFAULT_SETTINGS` with hardcoded `"delay": 1` (parameterize)
- `grade.py:193` — already resolves BRAIN's *actual* returned delay (fixed
  2026-06-11; add the requested-vs-returned comparison + warning here)
- `find_alphas.py:71` — `delay = thesis.get("delay", 1)` (thread `--delay`)
- `researcher.py:103` — catalog query filters `delay=1` datafields (must support
  delay=0 slice when requested)
- `run_delay0.py` — ad-hoc script to harvest then retire (D-05)
- `hunt.py` — add `--delay` CLI option (success criterion 3)

### Memory (project facts)
- Memory `brain-delay-recording-mismatch` — full account of the recording bug,
  the 11 mislabeled alphas (all BRAIN=delay-1), the 2026-06-11 fix, and the
  standing rule: a delay-0 request is not a delay-0 alpha until BRAIN's RESPONSE
  confirms `delay=0`.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `grade.py:193` resolution logic (`brain_settings.get("delay", active_settings.get("delay"))`)
  already pulls BRAIN's actual delay — the comparison/warning hooks onto this exact spot.
- `run_delay0.py` end-to-end auth→thesis→validate→simulate flow is a working
  reference for how a delay-0 sim is currently attempted (study before retiring).
- `test_grade_records_brain_actual_settings` — existing regression test for the
  recording fix; extend it for coercion-warning behavior.

### Established Patterns
- BRAIN is the source of truth; never trust the request (mirrors the no-hardcoded-
  thresholds rule). The whole phase is an instance of this pattern applied to delay.
- All BRAIN traffic runs on one shared authenticated session at concurrency ≤3,
  with no in-loop re-auth — the probe sim and hunt sims must reuse that session.

### Integration Points
- CLI (`hunt.py`, future `/bruteforce`) → `find_alphas.py` / orchestrator →
  `grade.py` simulate call → BRAIN. `--delay` must flow through every hop with
  delay-1 as the default and no silent override.
</code_context>

<specifics>
## Specific Ideas

- "But I can run it in my BRAIN UI though?" — the pivotal user observation that
  reframed the phase from "is delay-0 allowed?" (answered: yes) to "why doesn't
  our CODE get delay-0?" (answer: our request likely doesn't match the UI's).
- Confirmed delay-0 fields claimed by `run_delay0.py` (to RE-verify, not trust):
  `volume, vwap, nws12_afterhsz_sl, open, close`.

### CAPTURED UI delay-0 request (2026-06-12, the ground-truth payload)

User captured the actual `POST https://api.worldquantbrain.com/simulations`
body the BRAIN web UI sends for a delay-0 sim (USA/D0/TOP3000):

```json
{"type":"REGULAR","settings":{"nanHandling":"OFF","instrumentType":"EQUITY","delay":0,"universe":"TOP3000","truncation":0.08,"unitHandling":"VERIFY","testPeriod":"P1Y","pasteurization":"ON","region":"USA","language":"FASTEXPR","decay":3,"neutralization":"SUBINDUSTRY","visualization":false},"regular":"vwap"}
```

Confirmed facts:
- `delay` is an **integer** (`0`), nested **inside `settings`** — same placement
  our SDK already uses. Placement is NOT the bug.
- Endpoint: `POST https://api.worldquantbrain.com/simulations`. Top-level keys:
  `type` ("REGULAR"), `settings` (object), `regular` (expression string).
- The UI's `settings` has **13 keys** and does **NOT** include `maxTrade`.

### CAPTURED UI delay-1 request (2026-06-12) — the proof

User also captured the UI's **delay-1** POST body:

```json
{"type":"REGULAR","settings":{"nanHandling":"OFF","instrumentType":"EQUITY","delay":1,"universe":"TOP3000","truncation":0.08,"unitHandling":"VERIFY","testPeriod":"P1Y","pasteurization":"ON","region":"USA","language":"FASTEXPR","decay":3,"neutralization":"SUBINDUSTRY","visualization":false},"regular":"rank(vwap)"}
```

**DEFINITIVE FINDING:** the UI's delay-0 and delay-1 payloads are **identical
except the single `delay` integer (1 vs 0)**. BRAIN has no special "delay-0
mode" — the website just flips the number. Therefore the correct method in code
is: take ONE canonical settings object and set `delay` to the requested value.
The captured delay-0 object is a KNOWN-GOOD configuration (user ran it; it
returned a real delay-0).

### Payload diff: UI vs our `grade.py` `_BASE_SETTINGS` (grade.py:44-59)

| Setting | UI sends | Our code | Note |
|---|---|---|---|
| `maxTrade` | absent | `"ON"` | extra key UI omits — tolerated at delay-1 (our 441 alphas prove it); only suspect IF delay-0 coercion persists |
| `decay` | `3` | `15` | our choice; tolerated at delay-1 |
| `testPeriod` | `P1Y` | `P1Y6M` | our choice; tolerated at delay-1 |
| `delay` | `0`/`1` | `1` | same place/type ✓ |
| all others | — | — | match ✓ |

`decay`/`testPeriod` are independent knobs (keep our values). `maxTrade` is the
only structural extra. None is proven to break delay-0 — test, don't assume.


<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (Downstream delay-0 *usage* —
`--delay` in `/hunt` selection logic and `/bruteforce`, additivity gating — is
already scoped to Phases 6–8 in the roadmap, not deferred here. Phase 5 only
delivers the plumbing + feasibility verification those phases depend on.)

</deferred>

---

*Phase: 5-Delay-0 Feasibility & Plumbing*
*Context gathered: 2026-06-12*
