---
title: Grounded Alpha Discovery System — Design
created: 2026-06-07
revised: 2026-06-07 (after independent verifier red-team)
status: design-verified
supersedes: popsukss/alpha-generator (improves on it)
---

# Grounded Alpha Discovery System

A self-researching WorldQuant BRAIN alpha pipeline that **reasons over verified
knowledge + persistent memory**, instead of guessing. Built in `~/quant`.

> **Revision note:** this doc was red-teamed by an independent verifier agent on
> 2026-06-07. It caught a fabricated self-correlation endpoint (BLOCKER) plus
> several correctness/efficiency issues. All fixes are folded in below; the
> changelog is at the end.

## Why this exists (vs. popsukss/alpha-generator)

popsukss runs `Research → Ideation → Backtest → Editor → loop` entirely from the
model's imagination. Three structural flaws we fix:

1. **Ungrounded operators/fields.** popsukss lets the model invent FastExpr
   operators and data-field names → silent failures. **We pull the authoritative
   catalog from BRAIN's API, store it, and validate every expression against it
   locally before spending a simulation.**
2. **No memory.** Every popsukss run starts cold; it re-discovers and re-fails the
   same ideas. **We persist every alpha + result in SQLite, so iteration N knows
   what 1…N-1 found, and we never re-test a duplicate.**
3. **Hardcoded thresholds it never reconciles with BRAIN.** popsukss hardcodes a
   *screening* threshold (`sharpe>=1.0`) and never reads BRAIN's actual per-settings
   check limits, so it can call an alpha "PASS" that BRAIN will reject. **We read
   the `limit` and `result` of every check straight from BRAIN's `is.checks` array
   — BRAIN is the source of truth, we don't hardcode numbers.**

## Core principle: division of labor

| Job | Who |
|-----|-----|
| Generate ideas grounded in real operators/fields | our agents (Phase 2+) |
| Validate FastExpr syntax + grounding BEFORE simulating | our local validator |
| Run backtest, compute all checks, decide submittable | **BRAIN API** |
| Remember every result + correlations, avoid duplicates | our SQLite |
| Diagnose *why* a check failed + propose a fix | our Editor agent (Phase 3) |
| Pick (later: optimize) settings per alpha archetype | Settings Optimizer (Phase 4) |

We never *declare* an alpha submittable. We generate candidates and ask BRAIN to
grade them, then remember the grades.

## Architecture

```
        ┌─────────────── KNOWLEDGE BASE ───────────────┐
        │  SQLite (alpha_kb.db)      Obsidian vault     │
        │  • operators (from API)    • theses           │
        │  • data fields (from API)  • archetype rules  │
        │  • settings options        • "why X failed"   │
        │  • alpha history + stats   • factor research  │
        │  • normalized checks + correlations           │
        └───────────────────────────────────────────────┘
                 ▲ reads                    ▲ writes learnings
   ┌─────────────┴──────────────────────────┴─────────────┐
   │                  THE LOOP (per run)                   │
   │  ① Researcher → ② Ideator → ③ Backtester → ④ Editor   │
   │     (Sonnet)     (Sonnet)   (pool ≤3,       (Sonnet)  │
   │                              one session)             │
   │         ▲___________________ loop ×N _________________│
   └───────────────────────────────────────────────────────┘

   Phase 1 has NO LLM in the loop: seed list → validate → simulate → check → store.
```

### Agents / components
- **Sync** (script, not an agent) — pulls operators (`GET /operators`), data fields
  (`GET /data-fields`, paginated per dataset/region/delay/universe), settings
  options, and the user's submitted/OS alphas → SQLite. Run once; refresh
  occasionally. (Phase 1 does NOT fetch per-alpha PnL — see self-correlation below.)
- **Local validator** — rejects expressions whose operators/fields aren't in the
  synced catalog, or with malformed syntax (parens/arity), *before* any simulation.
  This is the single biggest efficiency win: sims are ~2 min and rate-limited.
- **① Researcher** (Sonnet, Phase 2) — picks a thesis, grounded by the real catalog
  + past results in the DB. Writes thesis prose to Obsidian.
- **② Ideator** (Sonnet, Phase 2) — turns thesis into FastExpr expressions using
  **only** verified operators/fields; tags each with an `archetype`; dedupes vs DB.
- **③ Backtester** (Phase 1: plain script; later a bounded worker pool **≤3**,
  sharing the ONE authenticated session) — runs simulate + check, writes to SQLite.
  **Never re-authenticates inside the loop** (see throttle gotcha).
- **④ Editor** (Sonnet, Phase 3) — classifies PASS / NEAR / FAIL from BRAIN's
  checks, diagnoses *which* check failed, proposes expression (later: settings)
  mutations. This is effectively a 1-step search rollout; upgradeable to MCTS/genetic.
- **Settings Optimizer** (Phase 4) — knowledge-driven, not blind sweep. See below.
- **Verifier** — a *one-shot build-time critic* over the finished code+plan.
  **Optional / low priority:** the 2026-06-07 red-team review already served as the
  first pass; we may just re-run that pattern by hand instead of building a component.

## Orchestration, cost & portability (Model A → B)

**Who runs the loop?** Two models:
- **Model A — Claude Code orchestrates (what we build).** A slash command (e.g.
  `/find-alphas`) drives the loop; Researcher/Ideator/Editor are Claude Code
  subagents; the deterministic parts (sync/validate/grade) are Python scripts the
  agents call. **The LLM is the Claude Code session itself — no separate API key.**
- **Model B — standalone daemon (possible later).** A `main.py` runs the loop and
  calls the Anthropic API (or a local model) directly; can run headless / 24-7.

**We build A** because: (1) the periodic Persona **biometric needs a human**, so true
fire-and-forget is blocked regardless; (2) Claude Code is already the LLM — no extra
plumbing or per-token bill; (3) you stay in the loop for the "is this decent?" call.

**Usage:**
```
Phase 1 (engine, semi-manual):
  python sync.py               # build the knowledge base (one-time / refresh)
  python grade.py ideas.txt    # validate → simulate → check → store; ranked table
Phase 2+ (full loop, Claude Code drives):
  /find-alphas --thesis "..."  # complete Persona once → loop → ranked submittable list
```

**Cost (Model A):**
- **LLM tokens** — the only real cost, kept low by design: the Backtester is a script
  (**0 tokens**); only Researcher/Ideator/Editor spend tokens, reading SQLite
  *summaries* not raw dumps. Order ~150–300k tokens/run. On a Claude **subscription
  (Pro/Max) this is covered by your included usage — no extra charge**, bounded only
  by your plan's rate limits. Per-token billing applies *only* if Claude Code runs
  against an Anthropic **API key**, or in Model B.
- **BRAIN API** — **$0** (free on your account; rate-limited, not billed).
- **Real bottleneck** — time: ~2 min/sim, concurrency ≤3. Time, not money.

**A → B portability:** the entire deterministic engine (sync / validate / grade / db /
schema / endpoints / `wq_login.py`) and the agent *prompts* carry over **unchanged**.
Only the loop driver is rewritten (Claude Code subagents → `main.py` + Anthropic API;
the Claude Agent SDK makes this standard) and the **biometric auth** must be solved
for unattended runs (the genuinely hard part — orthogonal to orchestration).
**De-risk now:** keep agent prompts as reusable prompt files so both A and a future B
call the same templates.

## Submittability = ask BRAIN (two phases)

`autobrain-sim` only wraps simulate/get_alpha/get_pnl/get_recordset — everything
below marked ★ is **hand-written** against raw endpoints.

**Phase A — simulate, read the cheap IS checks:**
```
POST /simulations → poll Location → GET /alphas/{id} → alpha["is"]["checks"]
```
`is.checks` is an array of `{name, result: PASS|FAIL|WARNING, limit, value}`.
After a bare simulation it contains the IS-stat gates (e.g. LOW_SHARPE, LOW_FITNESS,
LOW_TURNOVER, HIGH_TURNOVER, CONCENTRATED_WEIGHT, LOW_SUB_UNIVERSE_SHARPE,
MATCHES_COMPETITION, units/unitHandling). **`SELF_CORRELATION` and `PROD_CORRELATION`
come back `PENDING` here** — a bare sim does NOT compute them.

**Rules (don't hardcode!):** iterate over *whatever* checks BRAIN returns; treat any
`result == FAIL` as blocking; read each gate's `limit` from the check itself (the
LOW_SHARPE limit is delay-dependent — ≈1.25 at delay-1, higher at delay-0 — so we
read it, never hardcode 1.25). The list above is **non-exhaustive** by design.

**Phase B — resolve correlations (only for IS survivors):**
```
★ POST /alphas/{id}/check  → poll GET /alphas/{id} until SELF_CORRELATION /
   PROD_CORRELATION leave PENDING → read check["value"] from is.checks
```
This is a second ~minutes-long async op (budget for it; run only on survivors).
- **SELF_CORRELATION** = correlation vs *your own* submitted alphas.
- **PROD_CORRELATION** = correlation vs the whole production book (the hard one).
- Threshold is **configurable** (default 0.7; reference impls use 0.6) and
  **region-scoped** (only compare same-region alphas). Store the raw value so we can
  re-threshold without re-simulating.

Cheaper local alternative (Phase 3+): download PnL via the SDK's `get_pnl()`,
convert to returns, `corrwith().max()` vs cached same-region OS alphas. Avoids the
async `/check` round-trip but needs per-alpha PnL plumbing.

```
simulate → IS checks all PASS? ──no──► NEAR / FAIL  → Editor diagnoses
   │ yes
   ▼
POST /check → poll → SELF_CORRELATION & PROD_CORRELATION
   ≥ threshold ──► duplicate, reject (not "decent")
   < threshold ──► ✅ genuinely submittable
```

"**Decent**" = passes all checks **with margin** (Sharpe comfortably above the
returned limit) AND low self/prod correlation (adds diversity). This is *why* the
memory layer is mandatory — a high-Sharpe duplicate is worthless.

Submission itself (★ `POST /alphas/{id}/submit`, expects 201) stays **manual /
human-gated** for now — run by the user on chosen winners. Not automated.

## Hand-written endpoints (SDK does not provide these)

| Purpose | Endpoint |
|---------|----------|
| Trigger server checks (resolves SELF/PROD_CORRELATION) | ★ `POST /alphas/{id}/check` then poll `GET /alphas/{id}` |
| Operators catalog | ★ `GET /operators` |
| Data-fields catalog | ★ `GET /data-fields?dataset.id=…&region=…&delay=…&universe=…` (paginated) |
| Settings options / region-universe constraints | ★ region/universe metadata endpoint |
| Submit (manual) | ★ `POST /alphas/{id}/submit` (201) |

Provided by SDK: `POST /simulations`, `GET /simulations/{id}`, `GET /alphas/{id}`,
`GET /alphas/{id}/recordsets/pnl`, auth (persona handled by `wq_login.py`).

## Settings handling

- **Stored per-alpha in SQLite** (every row records the exact settings that produced
  its stats — non-negotiable; stats are meaningless without settings).
- **Phase 1: fixed** `BASE_SETTINGS` (USA, TOP3000, delay 1, decay 15,
  neutralization SUBINDUSTRY, truncation 0.08, testPeriod P1Y6M).
- **Later (Phase 4): knowledge-driven Settings Optimizer** — when an alpha is tagged
  NEAR *with margin*, optimize *its* settings instead of brute-forcing:
  1. start from archetype heuristics (an editable Obsidian note): reversal → short
     decay (2–5); momentum → long decay (15–30); high-turnover → tame via decay↑ /
     neutralization change; noisy → stronger neutralization + lower truncation.
  2. bias toward settings that produced PASS for the same archetype in the DB.
  3. test a small set (3–4 configs). ⚠️ This multiplies the scarcest resource (sims)
     3–4× per candidate under a 2-min/throttled budget — gate it behind "already NEAR
     with margin," never run it speculatively.
  4. write outcome back → heuristics sharpen over time (the flywheel).
  - Valid settings *values* come from BRAIN's API → never propose an invalid config.

## SQLite schema (initial)

```sql
CREATE TABLE alphas (
  alpha_id        TEXT PRIMARY KEY,
  expression      TEXT NOT NULL,
  parent_alpha_id TEXT,                 -- mutation lineage (Editor flywheel)
  archetype       TEXT,                 -- reversal | momentum | value | ...
  region          TEXT, universe TEXT, delay INTEGER,
  decay           INTEGER, neutralization TEXT, truncation REAL,
  settings_json   TEXT,                 -- full settings blob
  sharpe          REAL, fitness REAL, turnover REAL,
  returns         REAL, drawdown REAL,
  margin          REAL,                 -- BRAIN IS metric: return per $ traded (bps)
  long_count      INTEGER, short_count INTEGER,
  self_corr       REAL, prod_corr REAL, -- filled after POST /check (Phase B)
  corr_checked_at TEXT,
  pnl_path        TEXT,                 -- cached PnL for local corr (Phase 3+)
  status          TEXT,                 -- tested|near|pass|submitted|rejected
  run_id          TEXT,
  created_at      TEXT
);
-- normalized so the Settings Optimizer can query WHICH check failed per archetype
CREATE TABLE checks (
  alpha_id   TEXT, name TEXT, result TEXT,
  value      REAL, limit_val REAL, checked_at TEXT,
  PRIMARY KEY (alpha_id, name)
);
CREATE TABLE operators  (name TEXT PRIMARY KEY, category TEXT, definition TEXT, signature TEXT);
CREATE TABLE datafields (id TEXT, description TEXT, dataset TEXT, region TEXT,
                         universe TEXT, delay INTEGER, type TEXT,
                         PRIMARY KEY (id, region, universe, delay, dataset)); -- wide PK: same id exists across universes/datasets
CREATE TABLE runs (run_id TEXT PRIMARY KEY, thesis TEXT, started_at TEXT,
                   iterations INTEGER, num_pass INTEGER, notes TEXT);
CREATE INDEX idx_alphas_expr ON alphas(expression);          -- dedupe
CREATE INDEX idx_alphas_arch ON alphas(archetype, status);   -- optimizer learning
```

## Obsidian vault layout

```
alpha-kb/                 (new, dedicated — NOT the user's existing vault)
  Theses/                 one note per thesis  → links to alpha_ids
  Archetypes/             editable settings heuristics per archetype
  Failures/               "why <family> failed in <universe>"
```
DB holds *facts/numbers*; Obsidian holds *ideas/why*. (No "Operators/" notes — the
operators table already covers that; a prose mirror has no consumer.)

## Phase breakdown (build order)

- **Phase 1 — MVP grading engine. NO LLM in the loop.**
  1. Sync catalog (operators, data-fields, settings options) + user's OS alphas → SQLite.
  2. **Local validator**: reject expressions whose operators/fields aren't in the
     catalog or whose syntax is malformed — before any sim.
  3. Two-phase grading over a hand-seeded idea list: simulate → read IS `is.checks`;
     for survivors, `POST /check` → poll → read SELF/PROD_CORRELATION.
  4. Persist alphas + normalized checks to SQLite. Concurrency ≤3, one shared
     session, no in-loop re-auth.
  *Deliverable: a runnable engine that grades a list against BRAIN's real checks
  (incl. correlation) and remembers them.* (Reuses `wq_login.py`; generalizes
  `test_sim.py` — but reads check limits instead of its hardcoded `sharpe>1.25`.)
- **Phase 2 — Grounded generation.** Researcher + Ideator agents reading catalog + memory.
- **Phase 3 — Smart iteration.** Editor (diagnose + mutate); memory-aware dedupe;
  local PnL self-corr pre-filter; Frequent Subtree Avoidance (mine frequent motifs
  from PASS alphas, instruct Ideator to avoid them → structural novelty pre-sim).
- **Phase 4 — Optimization + polish.** Knowledge-driven Settings Optimizer; quality/
  decay monitor (uses the time-stamped checks table); optional MCTS/genetic search;
  Obsidian prose layer.

## Ideas adopted from comparable systems (researched 2026-06-07)

- **Local catalog validation** (worldquant-miner Gen-Two `template_validator.py`) → Phase 1.
- **Two-phase server `/check`** (xiegengcai `checker.py`) → Phase 1 (the only correct
  way to get SELF/PROD_CORRELATION).
- **Frequent Subtree Avoidance** (Alpha Jungle, arXiv 2505.11122) → Phase 3.
- **Quality/decay monitoring** (Gen-Two `alpha_quality_monitor.py`) → Phase 4.
- **SQLite-backed storage + retrospect** (Gen-Two `storage/`) → validates our choice.
- **MCTS / genetic search** (Alpha Jungle / Gen-Two evolution) → Phase 3–4.
- *Skipped:* RAG paper-scraping (Brainiac) and the offline simulator (efJerryYang) —
  orthogonal to a first decent alpha; the local validator gets ~80% of the benefit.

## Reuse from current state

- `wq_login.py` — biometric-aware login (keep; system logs in once per run, reuses
  the hot session, never re-auths in the loop).
- `test_sim.py` — proves the simulate→wait→get_alpha chain. Phase 1 generalizes it to
  a list + check-reading. **Replace its hardcoded `sharpe>1.25 and fitness>1.0`** with
  reading the per-check `limit` from `is.checks`.
- Deps live in `~/quant/venv` (homebrew python3 is 3.14 and lacks the packages).

## Known gotchas (carried forward + added)

- Biometric (Persona) re-auth is periodic; **single-shot login only.** 429
  BIOMETRICS_THROTTLED on repeated attempts → 15–30 min lockout. **Never re-auth
  inside the loop**; a 401 stops the run and surfaces, it does not retry.
- All sims and `/check`s run on the ONE shared authenticated session. **Concurrency
  ≤3** (BRAIN also caps concurrent sim slots, ~3–10). popsukss's free parallel
  re-auth model does NOT apply to us.
- `SimulationResult.wait()` returns only progress JSON — call `get_alpha()` for stats.
- The SDK's `simulate()` has a buggy `regular` param (double-assigns `payload["regular"]`,
  can silently drop the expression). **Always call `simulate(expr)` with the default
  `regular`**, or POST `/simulations` directly.
- `SELF_CORRELATION`/`PROD_CORRELATION` are PENDING until `POST /check`; a bare sim
  never resolves them.
- `autobrain-sim` has no operators/datafields/check/correlations/submit methods —
  all hand-written.

## Changelog

- **2026-06-07 v2 (post-verification):** fixed self-correlation endpoint (was a
  fabricated `GET /correlations/self`; real flow is `POST /check` → poll → read
  `is.checks`); made checks two-phase; stopped hardcoding check list + thresholds
  (read `limit`s); added PROD_CORRELATION; added local validator + concurrency cap
  to Phase 1; expanded schema (`parent_alpha_id`, `prod_corr`, `corr_checked_at`,
  `pnl_path`, normalized `checks` table, wider `datafields` PK); flagged Settings
  Optimizer sim cost; cut Obsidian Operators/ notes; noted SDK `simulate()` bug;
  downgraded the standing Verifier agent to optional.
- **2026-06-07 v1:** initial design from brainstorming session.
