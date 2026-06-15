# Phase 7: Brute-Force Tool (Tool B) - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

A standalone, **AI-free** in-repo tool (`/bruteforce`) that discovers *additive* alphas by combinatorial enumeration — runnable even when the Claude Code AI quota is exhausted, using only the cached BRAIN session.

Pipeline: **enumerate** parameterized templates (expression *and* settings slots) → **local validate** every combo (drop unknown tokens, counted) → **probe-sim** a small spread sample (abandon dead template shapes) → **bulk-sim** survivors at ≤3 concurrent on the one shared session → **additivity gate** (reuse Phase 6) → record **survivors + structured failure-reasons**. No second BRAIN login, no auto-submit; submission stays manual.

**In scope:** the `/bruteforce` command + engine (`bruteforce.py`), a `templates.py` template module shipping the 4 ACE-inspired shapes, catalog-grounded slot expansion, probe/abandon logic, quota-aware bulk sim, failure-aggregate persistence, and reuse of existing validate/grade/optimizer/additivity primitives.
**Out of scope:** `/hunt` evolution + `--research-only` fold (CMD-01/CMD-02, Phase 8); `/iterate` decorrelate mode (CMD-03, Phase 9); a shared sim-queue for true Tool A+B simultaneity (deferred v1.2); the LLM learning/memory loop over brute-force survivors (deferred v1.2); any auto-submission.
</domain>

<decisions>
## Implementation Decisions

### Template definition & shapes (BF-01)
- **D-01:** Templates are defined as **in-repo Python data structures** in a new `templates.py` module — mirroring the existing `delay0_candidates._D0_CANDIDATES` and `optimizer.ARCHETYPE_HEURISTICS` patterns. No YAML/JSON parser, no CLI-only definition: version-controlled, AI-free, and expressive enough for slot logic.
- **D-02:** Ship **all 4 ACE-inspired template shapes** pre-loaded — sentiment, fundamental, residual, beta — so `/bruteforce` has an immediate working run and copyable examples. Borrowed as *shapes only* (not ACE's runtime / relogin / auto-submit).
- **D-03:** A template's **field slot can declare a catalog filter** (e.g. `dataset='sentiment'`, `type='MATRIX'`) that auto-expands to all matching synced fields, **or** list literal tokens. Catalog-query is the default for breadth; literals pin a curated set. `validate.py` still gates every enumerated combo as a backstop so zero unknown-token combos reach simulation.
- **D-04:** A template can also enumerate **settings slots** (e.g. `neutralization`, `decay`, `truncation`) alongside expression slots — "settings = just more variables to enumerate" (design doc). Reuse `optimizer.py`'s variant logic as a **library** to build the settings grid; the full enumeration is the cartesian product of expression-slots × settings-slots.

### Probe gate (BF-03)
- **D-05:** A template is **kept** if ≥1 of its probe sample sims cleanly (no BRAIN ERROR) **and** reaches at least **NEAR** status. It is **abandoned** (logged: "template abandoned after probe") only when every probe errors or is a far FAIL — then the remaining combos for that template are skipped, spending no further sim slots.
- **D-06:** The probe sample is chosen to **spread across slot values** (cover every distinct slot value at least once), not first-N or pure-random — a far stronger test of whether *any* part of the template is viable. Default sample size **5**, configurable via `--probe-size`.

### Stop conditions & quota (BF-04)
- **D-07:** Quota is counted in **additive survivors** — alphas that pass all IS checks **AND** clear the additivity gate. Default quota **5** (matches design's "5 additive delay-0 alphas"), configurable via `--quota`. IS-pass-but-correlated does NOT count toward quota.
- **D-08:** `/bruteforce` defaults to **delay-0** (the primary diversification lever — a delay-0 alpha is structurally decorrelated from the heavily-delay-1 book, the most likely to be additive). Overridable via `--delay 1`. Threaded through the existing Phase-5 `--delay` plumbing.
- **D-09:** Templates are processed **sequentially, one fully before the next**, in listed order (probe → bulk-sim survivors → gate → collect). The run stops cleanly on any of: **quota met**, **401 session expiry**, or **dry** (no templates left). On 401 the tool **persists everything graded so far and reports partial progress** (templates done, quota count, stop point) — it **never re-authenticates in-loop** (401 is the natural budget ceiling).

### Failure-record schema (BF-06)
- **D-10:** **Survivors** are persisted as full rows in the existing `alphas` + `checks` tables (so the additivity gate, decay monitor, and selfcorr all see them via the normal schema). **Failures** are stored as **per-(run, template) aggregates** — counts by failure class (validate-dropped, sim-error, IS-fail-by-which-check, gate-fail-correlated) plus a few representative example expressions per class — **not** one row per dead combo (avoids DB landfill).
- **D-11:** Add a dedicated **`bruteforce_runs` table** for the per-template failure aggregates + run params (template, delay, quota, n_combos, n_validated, n_simmed, failure_counts JSON, examples JSON, quota_hit). The existing `runs` table gets one row per `/bruteforce` invocation. Keeps Tool B bookkeeping out of the alpha rows.

### Claude's Discretion
- The execution mechanics of "quota-met stops mid-flight at ≤3 concurrent" — whether to reuse `grade.grade_many` as-is or add a streaming/quota-aware scheduler variant — is left to the researcher/planner. The constraint is fixed: ≤3 concurrent, one cached session, stop cleanly without losing graded work.
- Exact `bruteforce_runs` column types/indexes, the precise CLI flag set, and the 401-detection mechanism (where in the grade path the 401 surfaces) are planner choices.
- The numeric definition of "far FAIL" for probe-abandon (vs NEAR) should reuse the existing Editor `classify_from_checks` NEAR/FAIL vocabulary rather than a new magic threshold.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 7: Brute-Force Tool (Tool B)" — goal, dependencies (Phase 5 delay, Phase 6 gate), 5 success criteria
- `.planning/REQUIREMENTS.md` — BF-01..BF-06 (brute-force generation); DLY-01/02 (delay plumbing, prereq); ADD-01..04 (additivity gate, reused)

### Design intent (Tool B)
- `docs/plans/2026-06-11-additive-alpha-discovery-design.md` — §"Tool B — Brute-force" (template→validate→probe→bulk→gate; ACE shapes as inspiration only; absorbs `/optimize` settings-variant logic), §"Candidate flow", §"Why not run them simultaneously" (shared single session), §"Command consolidation" (`/optimize` demoted to library)

### Reused decisions from prior phases
- `.planning/phases/06-additivity-gate/06-CONTEXT.md` — the additivity gate this phase calls; D-03 "the book" = submitted/active alphas only; gate is reusable as filter (bool) and score (float)
- `.planning/phases/05-delay-0-feasibility-plumbing/05-CONTEXT.md` — `--delay` threading + coercion detection that Tool B inherits

### Project constraints (BRAIN truth)
- `CLAUDE.md` §Constraints — single-shot auth / never re-auth in-loop (401 stops cleanly); ≤3 concurrent sims on one shared session; read check `result`/`limit` from `is.checks` (never hardcode 1.25/0.7); `simulate()` `regular` param is buggy (use default)
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `validate.validate(conn, expression)` (validate.py:23) — local catalog/syntax gate; called on **every** enumerated combo before any sim (BF-02). Returns `(bool, reason)`.
- `grade.grade_one(...)` (grade.py:108) / `grade.grade_many(...)` (grade.py:404) — the only BRAIN-sim + IS-check primitives; ≤3 concurrent, delay-aware, records BRAIN's actual returned settings/delay. Basis for probe-sim and bulk-sim.
- `optimizer.build_variants(alpha_row, conn)` (optimizer.py:94) + `optimizer.ARCHETYPE_HEURISTICS` (optimizer.py:42) — settings-variant logic reused as a **library** for D-04 settings slots; `/optimize` is demoted to library use.
- `additivity.rank_by_proxy(...)` (additivity.py:174) + `additivity.confirm_additive(...)` (additivity.py:260) — the Phase-6 gate; rank survivors by local PnL proxy then confirm finalists with the real BRAIN `/check`.
- `hunt._apply_additivity_gate(client, all_pass_ids, conn)` (hunt.py:86) — existing reference wiring of the gate into a submit path; Tool B mirrors this so both tools gate identically.
- `delay0_candidates._D0_CANDIDATES` (delay0_candidates.py:48) — structural model for the new `templates.py` in-repo data module (D-01).

### Established Patterns
- Graceful degrade: selfcorr/grade/additivity return `None`/`[]` on missing data rather than raising — Tool B's failure path follows this (a stale PnL or one sim error never aborts the whole run).
- BRAIN-as-truth: limits come from `is.checks`/DB, never literals — the probe NEAR/FAIL classification and gate both derive from BRAIN's returned limits.
- Editor `classify_from_checks` (editor.py) NEAR/FAIL/PASS vocabulary — reused for the probe-abandon "far FAIL" judgment (D-05), not a new threshold.

### Integration Points
- New `bruteforce.py` engine + `.claude/commands/bruteforce.md` command (parallels `hunt.py`/`hunt.md`).
- New `templates.py` module (4 ACE shapes).
- New `bruteforce_runs` table in `db.py` schema + CRUD (D-11); survivors reuse existing `alphas`/`checks` upsert paths.
- Reuses `wq_login.py` cached session — **no second login**.
</code_context>

<specifics>
## Specific Ideas

- The 4 template shapes come from ACE (`JediNakDev/wq-alpha-sim`): **sentiment, fundamental, residual, beta** — borrowed as *shapes only*. Explicitly NOT borrowing ACE's `relogin.py` (lockout risk) or its auto-submit (score-tanking risk).
- delay-0 default is deliberate: the IQC2026 team book is heavily delay-1, so delay-0 alphas are decorrelated almost by construction — the cheapest path to additivity. (Context: submitting the over-correlated `1Ygw09oz` dropped the team d1 score ~112 — the failure that made additivity the objective.)
- "AI-free" is a hard requirement (BF-05): the entire run — enumeration, validate, probe, bulk-sim, gate, record — must complete with the LLM absent, invoked purely against the cached BRAIN session.
</specifics>

<deferred>
## Deferred Ideas

- **Shared sim-queue for true Tool A + Tool B simultaneity** — deferred to v1.2 (one tool at a time for now; brute-force saturates the 3 slots anyway).
- **LLM learning/memory loop** distilling brute-force survivors + failure-reasons into future template design — deliberate later phase (v1.2); Phase 7 only *records* the structured data so a future loop can consume it, with FSA/diversity pressure to avoid reconverging on correlated motifs.
- **`/hunt` evolution & `/find-alphas` fold** (CMD-01/02) — Phase 8.
- **`/iterate` decorrelate mode** (CMD-03) — Phase 9.

</deferred>

---

*Phase: 7-brute-force-tool-tool-b*
*Context gathered: 2026-06-15*
