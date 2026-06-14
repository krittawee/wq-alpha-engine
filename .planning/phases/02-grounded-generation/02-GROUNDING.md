---
phase: 02-grounded-generation
title: Phase 2 Grounding Brief — Grounded Generation
date: 2026-06-08
status: grounding
---

# Phase 2 Grounding Brief

Phase 2 builds two new flat modules in `/Users/winter.__.kor/quant/` — `researcher.py` (produces a grounded thesis note) and `ideator.py` (turns the thesis into FastExpr candidates) — plus a `/find-alphas` Claude Code command that orchestrates them. The differentiator vs. the reference tools (popsukss, worldquant-miner) is **pre-simulation grounding against BRAIN truth**: every operator/field token is read from the live-synced `operators`/`datafields` tables in `alpha_kb.db`, every candidate is gated through `validate.validate()` and deduped via `db.expr_exists()` *before* spending a scarce ~2-min sim slot, and every thesis cites real past-alpha numbers from SQLite. The catalog is fully populated and verified (67 operators, 8155 datafields, 384 prior alphas) — Phase 2 is pure consumption of Phase 1's KB plus prose generation. This brief is grounded in direct queries against `/Users/winter.__.kor/quant/alpha_kb.db` run on 2026-06-08; where a research finding conflicted with the live DB, the DB wins and the correction is flagged inline.

## Catalog inventory (grounded building blocks)

DB: `/Users/winter.__.kor/quant/alpha_kb.db` (the task's `undefined/` prefix = repo root `/Users/winter.__.kor/quant/`). Present and populated. Tables and live counts (verified 2026-06-08):

| Table | Rows | Role in Phase 2 |
|---|---|---|
| `operators` | 67 | grounding source for operator tokens (validator matches `operators.name`) |
| `datafields` | 8155 | grounding source for field tokens (validator matches `datafields.id`) |
| `alphas` | 384 | dedup target (`alphas.expression`) + past-result insight source |
| `checks` | 40 (5 distinct alphas) | per-check `result`/`limit` evidence (all naive failures) |
| `runs` | 0 | empty — Phase 2 may begin writing thesis-run rows |

There is **no `settings` table**. Region/universe/delay are columns on `datafields` and `alphas`. All 8155 datafields are **region=USA, universe=TOP3000, delay=1** (single slice synced) — do NOT assume other slices exist.

**Operators (67) — 7 categories.** Call signatures live in `operators.definition`; the `operators.signature` column is EMPTY for all 67 rows (read `definition`).

| Category | Count | Operators |
|---|---|---|
| Time Series | 24 | ts_zscore, kth_element, ts_sum, ts_std_dev, ts_scale, ts_rank, ts_quantile, ts_mean, ts_delta, ts_step, ts_delay, ts_backfill, ts_av_diff, ts_arg_min, ts_arg_max, ts_corr, days_from_last_change, ts_count_nans, hump, ts_covariance, ts_decay_linear, ts_product, ts_regression, last_diff_value |
| Arithmetic | 15 | add, subtract, multiply, divide, min, max, abs, sign, signed_power, power, sqrt, log, inverse, reverse, densify |
| Logical | 11 | if_else, and, or, not, equal, not_equal, greater, greater_equal, less, less_equal, is_nan |
| Cross Sectional | 7 | rank, zscore, scale, winsorize, normalize, quantile, vector_neut |
| Group | 6 | group_neutralize, group_rank, group_zscore, group_mean, group_scale, group_backfill |
| Vector | 2 | vec_sum, vec_avg |
| Transformational | 2 | trade_when, bucket |

Key signatures (verbatim from `operators.definition`): `ts_rank(x, d, constant = 0)`, `ts_corr(x, y, d)`, `ts_regression(y, x, d, lag = 0, rettype = 0)`, `ts_decay_linear(x, d, dense = false)`, `ts_delta(x, d)`, `ts_zscore(x, d)`, `rank(x, rate=2)`, `winsorize(x, std=4)`, `vector_neut(x, y)`, `group_neutralize(x, group)`, `group_rank(x, group)`, `group_mean(x, weight, group)`, `trade_when(x, y, z)`, `if_else(input1, input2, input3)`, `signed_power(x, y)`.

**Datafields (8155).** Types: MATRIX 6469, VECTOR 1534, GROUP 142, UNIVERSE 6, SYMBOL 4. VECTOR fields (e.g. `nws12_afterhsz_sl`) must be reduced via `vec_avg`/`vec_sum` before scalar use. 18 datasets; top by field count: model77(3256), analyst4(1324), fundamental6(886), news12(875), fundamental2(766), earnings4(375), pv13(165), model53(138), news18(121), option9(74), option8(64), pv1(24), model16(24), sentiment1(19), socialmedia12(18), model51(16), socialmedia8(4), univ1(6).

Representative confirmed field tokens (verified to exist in DB on 2026-06-08):
- **Price/Volume (pv1):** `close, open, high, low, volume, returns, vwap, cap, adv20, dividend, adjfactor, sharesout`.
- **GROUP fields for neutralization (all 7 confirmed bare tokens, type=GROUP):** `sector, subindustry, industry, market, country, exchange, currency`. (Correction: two findings claimed bare `sector`/`subindustry` were absent — the live DB confirms ALL SEVEN are present and type=GROUP. Prefer `industry`/`subindustry` per past-result evidence below.)
- **UNIVERSE flags (univ1):** `top200, top500, top1000, top2000, top3000, topsp500`.
- **Fundamentals:** `operating_income, debt_lt, bookvalue_ps, cashflow_op, revenue, assets` (all confirmed; `operating_income` and `debt_lt` are reused winners).
- **Analyst (analyst4):** `actual_eps_value_quarterly, actual_sales_value_annual, adj_net_income_avg/median/stddev`, `anl4_*` prefixed fields.
- **News/sentiment (VECTOR):** `nws12_afterhsz_sl` (the most-reused winning sentiment field; VECTOR → wrap in `vec_avg`).
- **GARP model field:** `mdl177_garpanalystmodel_qgp_vfpriceratio` (MATRIX; the qMXnEVQK signal).

**Catalog gotchas for the Ideator:**
- `operators.signature` is empty — read `operators.definition` for arity/args.
- Only USA/TOP3000/delay-1 is synced. The Ideator must filter datafields with `WHERE region='USA' AND universe='TOP3000' AND delay=1`.
- There is **no catalog-read helper in db.py** — the Ideator runs its own SELECTs (template in §Phase 1 integration contract).

## Past-alpha insights (reusable, citable)

`alphas` status split: UNSUBMITTED=363, ACTIVE=16 (user's live submitted), fail=5. Sharpe: min −1.91, avg 0.845, max 2.65. **Empty/NULL across all 384:** `archetype` (blank), `self_corr` (NULL), `prod_corr` (NULL). Resolved correlation numbers exist only in memory files, NOT in the DB — so any self_corr citation must come from memory, while sharpe/fitness/turnover/status citations come from `alphas`, and check pass/fail from `checks`.

**Clean submittable pool already in KB:** 135 UNSUBMITTED have Sharpe≥1.25 → 65 also Fitness≥1.0 → **59 also Turnover≤0.4**. A valid thesis hook is "mine/diversify around this existing 59-alpha pool rather than regenerate it."

**What WORKED (real expressions, citable provenance):**
- `qMXnEVQK` (memory) — GARP analyst price-ratio: `vector_neut(-1*mdl177_garpanalystmodel_qgp_vfpriceratio*ts_std_dev(...,30), rank(ts_std_dev(returns,252)))`. **Passes ALL IS checks**, Sharpe 1.62 / Fitness 1.79, **self_corr 0.3455 (<0.7)**, decay=5, SECTOR neut. The verified-submittable anchor alpha.
- `e7rnMqwp` (memory) — improved qMXnEVQK: adds `winsorize(signal, std=4)` + INDUSTRY neutralization → Sharpe 1.82, **self_corr 0.256**. Lesson: `winsorize(signal)` is the dominant self-corr-lowering lever (0.35→0.26) AND lifts Sharpe; `rank(signal)` destroys the magnitude; INDUSTRY/SUBINDUSTRY beat SECTOR.
- `rKAR6n61` (ACTIVE) — Sharpe 2.16, fit 1.43, turn 0.119: news-sentiment regime gate over `vec_avg(nws12_afterhsz_sl)` × volume ratio.
- `xAmKVJnn` (ACTIVE) — Sharpe 1.61, fit 1.54, turn 0.025: `-ts_corr(research_development_expense.../revenue, ts_delay(sales_growth,63), 252)`.
- `3qnM577Q` (ACTIVE) — Sharpe 2.04: `debt_lt` zscore/scale stack × `rank(-returns)`.
- `Jj5ZKPvm` (ACTIVE) — Sharpe 1.60: `rank(ts_rank(operating_income / cap, 120))`.
- Best UNSUBMITTED low-turnover family (`power(rank(ts_mean(volume,5)/ts_mean(volume,252))...`): `j21YWX3o` 2.07/1.46/turn0.138, `vRd1x9Oa`, `RRdEqevd`.

**Most-reused profitable building blocks** (frequency in Sharpe≥1.5 alphas): `vec_avg(nws12_afterhsz_sl)` (18×), `operating_income/{close,cap}` momentum (17×), `winsorize` (5×), `debt_lt` (3×), fundamental-pair `ts_corr`, `mdl177_garpanalystmodel_qgp_vfpriceratio` (GARP).

**What FAILED (status=fail, with BRAIN check values) — the exact anti-pattern to avoid.** All 5 are naive single-operator price/volume signals:

| alpha | expression | Sharpe | failing checks |
|---|---|---|---|
| P01nO8kp | `rank(ts_mean(returns,10))` | −0.42 | LOW_SHARPE, LOW_FITNESS, LOW_SUB_UNIVERSE_SHARPE |
| le07Wqr7 | `-rank(ts_mean(returns,5))` | 0.76 | LOW_SHARPE, LOW_FITNESS |
| bl9NQN2p | `zscore(volume/ts_mean(volume,20))` | 0.08 | LOW_SHARPE, LOW_FITNESS |
| omYnNEdl | `zscore(close-ts_mean(close,10))` | −1.15 | LOW_SHARPE, LOW_FITNESS, CONCENTRATED_WEIGHT(0.234>0.10) |
| RRrN7j7d | `rank(ts_mean(returns,20)/(ts_std_dev(returns,20)+0.0001))` | −0.59 | LOW_SHARPE, LOW_FITNESS, LOW_SUB_UNIVERSE_SHARPE |

**Live check limits observed in `checks`:** LOW_SHARPE 1.25, LOW_FITNESS 1.0, CONCENTRATED_WEIGHT 0.10, LOW_SUB_UNIVERSE_SHARPE per-alpha negative. SELF_CORRELATION 0.7 (memory). Note: `checks` SELF_CORRELATION rows are all `result=PENDING` — no resolved corr is stored in-DB.

**Fitness formula (memory, confirmed):** `Fitness = Sharpe × √(|Returns| / max(Turnover, 0.125))` — turnover below the 0.125 floor stops helping fitness.

**Citable thesis hooks (satisfy criterion 1's "≥1 insight from SQLite"):**
1. "Diversify away from price/volume reversal" — every status=fail alpha is a naive returns/volume operator; winners use sentiment/fundamentals/analyst data.
2. "Apply `winsorize(signal)` + INDUSTRY neutralization" — cut self_corr 0.35→0.26 while raising Sharpe (qMXnEVQK→e7rnMqwp, memory).
3. "Target the 59-alpha clean pool (Sharpe≥1.25, Fitness≥1.0, Turnover≤0.4)" — query `alphas` directly.

## Phase 1 integration contract

All Phase 1 modules are flat in `/Users/winter.__.kor/quant/`. `researcher.py`/`ideator.py` plug into these exact, source-verified signatures. **There is no catalog-read helper** — the Ideator/Researcher issue their own SELECTs.

**db.py (verified `file:line`):**
- `init_db(path: str = "alpha_kb.db") -> sqlite3.Connection` (`db.py:55`) — opens conn (WAL), creates tables/indexes; **caller owns/closes it**.
- `expr_exists(conn, expression: str) -> Optional[str]` (`db.py:149`) — **THE DEDUP HELPER (criterion 3)**. Internally `SELECT alpha_id FROM alphas WHERE expression=? LIMIT 1` (index `idx_alphas_expr`). Returns existing `alpha_id` (truthy) or `None`. Exact-string match, no normalization.
- `upsert_alpha(conn, alpha_dict: dict) -> None` (`db.py:69`) — INSERT OR REPLACE on `alpha_id` PK; keys are the 26 `_ALPHA_COLS` (`db.py:46-52`): `alpha_id, expression, parent_alpha_id, archetype, region, universe, delay, decay, neutralization, truncation, settings_json, sharpe, fitness, turnover, returns, drawdown, margin, long_count, short_count, self_corr, prod_corr, corr_checked_at, pnl_path, status, run_id, created_at`. Missing keys default to NULL. **Note: `archetype` is a writable column here** — the Ideator/grader can persist the archetype tag (criterion 3) on each row.

**Catalog-read SELECTs the Ideator/Researcher must run (no helper exists):**
```sql
-- operators (name is PK; read definition for signatures, signature col is empty)
SELECT name, category, definition FROM operators;
-- datafields (must filter the synced slice)
SELECT id, description, dataset, type FROM datafields
WHERE region='USA' AND universe='TOP3000' AND delay=1;
```
Only `operators.name` and `datafields.id` are validator-load-bearing.

**validate.py — the gate (criterion 2):**
- `validate(conn, expression: str) -> tuple[bool, str]` (`validate.py:23`). Returns `(True, "")` if valid; else `(False, reason)` fail-fast in order: `"empty expression"` → `"unbalanced parentheses"` → `"unknown operator: {token}"` (identifier immediately before `(`) → `"unknown data field: {token}"` (remaining identifier not in `_EXCLUSIONS` keyword set, `validate.py:16`). Pure numeric literals are never flagged. **Requires operators/datafields to be synced** (Phase 1 `sync.sync_all`, `sync.py:224`).

**Dedup query (criterion 3):** use `db.expr_exists(conn, expr)` — do NOT hand-roll the SELECT.

**Archetype tagging (criterion 3):** the tag is free-form metadata the Ideator attaches to each candidate (planner decides mechanism — see open questions). It can be persisted via the `archetype` column in `upsert_alpha`, and emitted in the thesis note's candidate table + frontmatter. The validator does not check archetype; it is a labeling/dedup-grouping concern.

**grade.py + cli.py — grading handoff (two integration points):**
- `grade_one(client, conn, expression: str, run_id: str) -> dict` (`grade.py:54`) — **already calls `db.expr_exists` (Step 0) then `validate.validate` (Step 1) internally** before simulating. Returns `{expression, status, alpha_id, is_survivor, sharpe, fitness, self_corr, prod_corr, checks}`.
- `grade_many(client, conn, expressions: list, run_id: str, max_workers: int = 1) -> list[dict]` (`grade.py:215`) — `max_workers` clamped ≤3 (`grade.py:228`).
- **Path A (file):** `ideator.py` writes candidates to a `seeds.txt`-style file (one FastExpr/line; blank lines and `#` comments ignored, `cli.py:62-64`), then `python cli.py <file> [--db PATH] [--sync] [--workers {1,2,3}]` (`cli.py:26`) consumes it — does single-shot `login()`, `init_db`, optional `sync_all`, `run_id=uuid4()[:8]`, then `grade_many`.
- **Path B (direct):** orchestrator passes Ideator's `list[str]` straight to `grade.grade_many(client, conn, expressions, run_id)`, reusing `client` from `wq_login.login()` and `conn` from `db.init_db`.
- Either way grade is the authoritative gate (re-validates + re-dedups); the Ideator's own `validate`/`expr_exists` calls are an early pre-filter to save sim slots.

**Imports needed:** `researcher.py` → `import db` (catalog SELECTs + insight queries). `ideator.py` → `import db, import validate` (+ `import grade` for Path B).

**Auth/concurrency constraints (from CLAUDE.md):** single-shot `wq_login.login()`, never re-auth in-loop (429 lockout risk); ≤3 concurrent sims on one shared session; `client.simulate(expression)` positional only, never `regular=`.

## Archetype taxonomy

8 archetypes; tag each candidate with one label: `reversal, momentum, value_garp, quality, growth, low_volatility, liquidity_volume, sentiment_event`. Skeletons are **pseudo-valid** — exact arg order, window counts, and field ids must pass `validate.validate()` and `db.expr_exists()` before grading. All operator/field tokens below are confirmed present in the live catalog unless flagged.

| Archetype | Grounded operators | Grounded fields | Skeleton FastExpr |
|---|---|---|---|
| reversal | ts_delta, ts_zscore, reverse, rank, zscore, hump, group_neutralize | returns, close, vwap, volume | `rank(reverse(ts_delta(close, 5)))` |
| momentum | ts_delta, ts_mean, ts_delay, ts_decay_linear, rank | close, returns | `rank(ts_decay_linear(ts_delta(ts_delay(close, 21), 231), 5))` |
| value_garp | divide, rank, zscore, winsorize, group_neutralize, multiply, sign, vector_neut | bookvalue_ps, cashflow_op, close, cap, actual_eps_value_quarterly, mdl177_garpanalystmodel_qgp_vfpriceratio | `group_neutralize(winsorize(rank(divide(bookvalue_ps, close)), std=4), industry)` |
| quality | divide, rank, zscore, winsorize, group_zscore, reverse | cashflow_op, assets, debt_lt, cash, operating_income | `group_zscore(rank(divide(operating_income, assets)), industry)` |
| growth | ts_delta, ts_regression, divide, rank, group_neutralize | actual_sales_value_annual, actual_eps_value_quarterly, adj_net_income_avg | `rank(divide(ts_delta(actual_sales_value_annual, 252), abs(ts_delay(actual_sales_value_annual, 252))))` |
| low_volatility | ts_std_dev, reverse, rank, vector_neut, group_neutralize | returns, historical_volatility_60, implied_volatility_call_60 | `rank(reverse(ts_std_dev(returns, 60)))` |
| liquidity_volume | ts_corr, ts_zscore, ts_av_diff, trade_when, divide, rank, power | volume, adv20, vwap, returns, sharesout | `trade_when(greater(ts_zscore(volume, 20), 1), rank(ts_corr(close, volume, 20)), -1)` |
| sentiment_event | vec_avg, ts_delta, ts_decay_linear, ts_mean, rank, zscore, group_neutralize, trade_when | nws12_afterhsz_sl (VECTOR→vec_avg), adj_net_income_avg, anl4_*_estvalue | `group_neutralize(rank(ts_decay_linear(ts_mean(vec_avg(nws12_afterhsz_sl), 5), 5)), industry)` |

**Steering notes:** always wrap the final signal in a cross-sectional normalizer (`rank`/`zscore`/`scale`) so output is tradeable. Prefer `industry`/`subindustry` neutralization (both confirmed; past results favor INDUSTRY/SUBINDUSTRY over SECTOR). For self-corr control on value/GARP, apply `winsorize(signal, std=4)`. Use `hump`/`ts_decay_linear` for turnover control on reversal/momentum. VECTOR fields (e.g. `nws12_afterhsz_sl`) MUST be reduced with `vec_avg`/`vec_sum`. `trade_when`'s first arg must be a boolean expression — use logical ops (`greater`, `less`, `equal`) not bare comparisons if the FastExpr parser requires it (verify against BRAIN at grade time).

## Obsidian thesis-note template

Vault: create a **new in-repo vault at `/Users/winter.__.kor/quant/alpha-kb/`** (per design doc `docs/plans/2026-06-07-alpha-system-design.md` lines 259-268 — explicitly NOT the user's personal vault at `/Users/winter.__.kor/Documents/Obsidian Vault`). Layout: `alpha-kb/Theses/` (Phase 2 emits here), `alpha-kb/Archetypes/` (Phase 4), `alpha-kb/Failures/` (Phase 3+). Note path: `alpha-kb/Theses/YYYY-MM-DD-<archetype>-<slug>.md`.

Frontmatter (every `source_operators` ⊆ `operators.name`; every `source_datafields` ⊆ `datafields.id` for the synced slice — machine-checkable for criterion 1):
```yaml
---
title: Volume-shock short-horizon reversal
date: 2026-06-08
status: proposed            # proposed | grading | graded | shelved
archetype: reversal         # one of the 8 taxonomy labels
run_id: <uuid4-8>           # FK -> runs.run_id (and alphas.run_id)
region: USA
universe: TOP3000
delay: 1
source_operators: [ts_mean, rank, zscore]      # MUST exist in operators.name
source_datafields: [close, volume, returns]    # MUST exist in datafields.id
cited_alpha_ids: [P01nO8kp, vR9QdJAd]          # FK -> alphas.alpha_id (provenance)
cited_insights:
  - "LOW_SHARPE is the most common FAIL (5 alphas, limit 1.25); thesis targets margin above it"
  - "Top sharpe to date is vR9QdJAd at 2.65 (UNSUBMITTED); no reversal alpha yet ACTIVE"
candidate_count: 4
tags: [thesis, alpha, reversal]
---
```

Body sections (in order): `# {title}` → `## Thesis` (one-paragraph claim: signal, horizon, edge) → `## Economic rationale` (why a real mechanism, 2-4 sentences — the "why" the DB can't hold) → `## Grounding: operators & fields cited` (markdown tables of cited operators with category/signature from `operators`, and fields with description/dataset/type from `datafields`, plus the line "Every token confirmed in synced catalog; validate.py rejects otherwise") → `## Past-result insight cited` (wikilinks `[[<alpha_id>]]` + prose tying ≥1 SQLite fact to the thesis; cite `sharpe`/`fitness`/`status`/`checks`, since `archetype`/`self_corr` are NULL in-DB) → `## Candidate expressions` (a fenced block in **exact seeds.txt format**, one FastExpr/line so grade.py/cli.py can lift it directly, followed by a table: `# | expression | archetype | dedupe(expr_exists)`) → `## Next steps` (checklist: queue to grade.py, update status, hand NEAR-with-margin to Phase 4).

**Linking loop:** note→SQLite via `cited_alpha_ids` (verifiable by re-running the source query) and `run_id` (FK to `runs`). Note→candidates via the seeds-format fenced block, each dedup-checked with `db.expr_exists()`. SQLite→note: when graded, write the note's relative path into `runs.notes` and tag resulting `alphas.run_id` — any alpha row traces back to its thesis.

## Lessons from reference tooling

**Borrow:**
- popsukss's clean agentic research→ideate→(edit) loop with run-scoped artifacts — good ergonomics to mirror in `/find-alphas` + `researcher.py`/`ideator.py`.
- worldquant-miner gen2's operator metadata model (arity/scope/lookback) — but we already have richer truth in the synced `operators` table; read `definition` for arity instead of a JSON snapshot.
- gen2's AST/operator-field compatibility pre-sim gate concept — we realize it more cheaply via Phase 1's `validate.validate()` (catalog-backed) as the mandatory gate.
- gen2's persistent dedup intent — we satisfy it with `db.expr_exists()` against persistent `alphas.expression` (both tools fail at cross-run memory; we have it).
- Editor/evolution "mutate verified winners" pattern — Phase 2 can seed from the 59-alpha clean pool and the qMXnEVQK→e7rnMqwp lineage (winsorize + industry neut) rather than rolling random structures (Phase 3 territory, but design the candidate format to support it).

**Failure modes to design against (and our mitigation):**
| Failure mode | Seen in | Phase 2 mitigation |
|---|---|---|
| Hallucinated/invalid operators, wrong arity | popsukss (LLM operator notes) | every operator token validated against `operators.name`; arity from `operators.definition` |
| Undefined / hardcoded-whitelist datafields | popsukss (10-field OHLCV list) | Ideator reads the full synced `datafields` (8155, USA/TOP3000/delay1); reject unknown tokens pre-sim |
| Random / semantically empty structure | gen2 (random walk + LLM index-pick) | structure comes from grounded archetype skeletons + thesis reasoning, not random math |
| No pre-sim gate → wasted ~2-min slots | popsukss (no gate); gen2 (partial) | mandatory `validate.validate()` + `db.expr_exists()` before any sim; grade.py re-checks as authoritative gate |
| Duplicate ideas across runs | both (no persistent memory) | `db.expr_exists()` against persistent `alphas.expression` (idx_alphas_expr) |
| Hardcoded thresholds drift from BRAIN | popsukss `screen.py` (sharpe/fitness/turnover constants) | never hardcode limits; read each check's `result`/`limit` from BRAIN `is.checks` at grade time (Phase 1 grade.py already does) |
| Correlation found late | both (post-sim only) | grade.py polls `POST /alphas/{id}/check`; thesis pre-filters against own ACTIVE set where possible |

## Proposed plan breakdown

1. **02-01 — `researcher.py` + insight queries.** Build the Researcher: read the catalog (`operators`/`datafields` SELECTs), run past-alpha insight queries against `alphas`/`checks` (sharpe/fitness/status, common FAIL checks, the 59-alpha clean pool), pick an archetype + thesis, and emit a grounded thesis Markdown note. Touches: `db.init_db`, catalog SELECTs, `alphas`/`checks` read queries, optional `runs` write.
2. **02-02 — `ideator.py` + archetype tagging + dedup.** Build the Ideator: consume a thesis note, compose FastExpr candidates from grounded archetype skeletons, gate each through `validate.validate(conn, expr)`, dedup via `db.expr_exists(conn, expr)`, and tag each with one of the 8 archetype labels. Output candidates in seeds.txt format. Touches: `validate.validate`, `db.expr_exists`, catalog SELECTs, archetype tagging (→ `archetype` column on later `upsert_alpha`).
3. **02-03 — `/find-alphas` command + Obsidian emit + vault scaffold.** Create the Claude Code command that orchestrates Researcher→Ideator, scaffold `alpha-kb/` (Theses/Archetypes/Failures), and emit the thesis note (frontmatter + body + seeds-format candidate block) to `alpha-kb/Theses/`. Touches: orchestration of 02-01/02-02 outputs, note template, `runs` row write (run_id, notes path).
4. **02-04 — end-to-end checkpoint.** Run `/find-alphas` against the live KB; verify all 3 success criteria: (1) note cites real catalog tokens + ≥1 SQLite insight, (2) validator rejects zero Ideator outputs for unknown tokens, (3) every candidate archetype-tagged and `expr_exists`-confirmed absent before queueing. Optionally hand a small batch to `grade.grade_many` (≤3 workers, single-shot login) as a smoke test. Touches: `validate.validate`, `db.expr_exists`, `grade.grade_many`/`cli.py`.

## Open questions for the planner

1. **Candidates per thesis:** how many FastExpr candidates should the Ideator emit per thesis (popsukss used 15-20)? Given the ≤3-concurrent-sim and slow-sim constraints, a smaller, higher-conviction set (e.g. 4-8) may be better. Needs a target number.
2. **Archetype tagging mechanism:** is the tag (a) chosen by the Researcher in frontmatter and inherited by all candidates, (b) chosen per-candidate by the Ideator, or (c) inferred by a classifier from operators/fields used? Affects how `archetype` flows into `upsert_alpha`.
3. **Vault location confirmation:** confirm `/Users/winter.__.kor/quant/alpha-kb/` (in-repo, version-controlled) vs. some other path; confirm it should be git-tracked. Design doc prescribes in-repo, but the human should ratify before scaffolding.
4. **Grading handoff path:** Path A (write seeds file → `cli.py`) vs. Path B (direct `grade.grade_many`). Does `/find-alphas` stop at thesis+candidates (human reviews, then runs grading separately), or auto-queue into grading? Affects auth/sim-slot timing.
5. **`runs` table usage:** Phase 2 has the first opportunity to populate the empty `runs` table (run_id, thesis path, notes). Should Phase 2 own writing `runs` rows, or defer to Phase 3? Confirm the `runs` schema/columns the Researcher should write.
6. **Researcher creativity vs. determinism:** is thesis/archetype selection LLM-driven (Claude Code agent prose) or deterministic (rotate through under-explored archetypes / target the clean pool)? Determines how much of `researcher.py` is code vs. agent prompt.
7. **Self-corr pre-filtering:** in-DB `self_corr` is NULL and `checks` SELF_CORRELATION is PENDING; only memory has resolved values. Should the Ideator attempt any self-corr pre-estimate (e.g. avoid expressions structurally near ACTIVE alphas), or rely entirely on grade.py's post-sim `POST /alphas/{id}/check`?

## Resolved decisions (human, 2026-06-08)

These resolve the open questions above. The planner MUST treat these as fixed constraints.

1. **Candidates per thesis = 4–8.** Ideator emits a small, high-conviction set sized to the ≤3-concurrent / ~2-min-per-sim / single-shot-auth constraints (one thesis = 2–3 sim waves).
2. **Grading handoff = STOP for human review.** `/find-alphas` emits thesis + dedup'd candidates only; it does NOT call grade/sim. Grading is run separately by the human (Path A: `python cli.py <seeds-file>`). Rationale: biometric-auth lockout risk + never-re-auth-in-loop. → Phase 2 does NOT import/invoke `grade.grade_many` in the `/find-alphas` path (the 02-04 checkpoint may run a manual smoke test, but the command itself stops at candidates).
3. **Researcher = HYBRID.** Deterministic code selects the archetype (rotate under-explored / target the 59-alpha clean pool) and pulls grounded catalog + past-result facts; an LLM agent writes the thesis prose / economic rationale. Steering is reproducible; justification is creative.
4. **Archetype tag = INHERITED from thesis.** Researcher sets one `archetype` in thesis frontmatter; all candidates from that thesis inherit it (one thesis = one archetype) and it flows into `upsert_alpha.archetype` at grade time. No per-candidate or classifier logic in Phase 2.

**Defaults accepted (no objection):**
5. **Vault = `/Users/winter.__.kor/quant/alpha-kb/`, git-tracked** (per design doc `docs/plans/2026-06-07-alpha-system-design.md`). Scaffold `Theses/`, `Archetypes/`, `Failures/` in 02-03.
6. **`runs` table = Phase 2 owns it.** Phase 2 begins populating the empty `runs` table (run_id, thesis note path, notes) — 02-03 writes a `runs` row per `/find-alphas` invocation. Planner confirms the `runs` schema/columns.
7. **Self-corr pre-filter = NONE in Phase 2.** Rely entirely on `grade.py`'s post-sim `POST /alphas/{id}/check`. Structural-similarity / FSA pre-filtering is deferred to Phase 3.
