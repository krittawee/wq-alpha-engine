# Phase 2: Grounded Generation - Research

**Researched:** 2026-06-08
**Method:** 6-agent parallel research workflow (catalog, past alphas, Phase 1 contract, reference tooling, archetype taxonomy, Obsidian format) → synthesized + DB-verified.
**Authoritative source:** `02-GROUNDING.md` in this directory. This file summarizes the planner-load-bearing facts; read `02-GROUNDING.md` for the full catalog inventory, full 8-archetype skeleton table, and the complete Obsidian template.

## Catalog (live-verified 2026-06-08 against alpha_kb.db)

- **67 operators**, 7 categories. `operators.signature` is EMPTY — read `operators.definition` for arity. Validator matches `operators.name`.
- **8155 datafields**, all region=USA / universe=TOP3000 / delay=1 (single synced slice). Validator matches `datafields.id`. Types: MATRIX 6469, VECTOR 1534 (must wrap in `vec_avg`/`vec_sum`), GROUP 142, UNIVERSE 6, SYMBOL 4.
- **No `settings` table** — region/universe/delay are columns on `datafields` and `alphas`.
- **No catalog-read helper in db.py** — researcher/ideator run their own SELECTs:
  ```sql
  SELECT name, category, definition FROM operators;
  SELECT id, description, dataset, type FROM datafields
  WHERE region='USA' AND universe='TOP3000' AND delay=1;
  ```
- All 7 GROUP neutralization fields confirmed present: `sector, subindustry, industry, market, country, exchange, currency`. Past results favor INDUSTRY/SUBINDUSTRY over SECTOR.

## Phase 1 integration contract (source-verified signatures)

All Phase 1 modules are flat in `/Users/winter.__.kor/quant/`. New code imports them directly.

- **`db.init_db(path="alpha_kb.db") -> sqlite3.Connection`** (db.py:55) — opens conn (WAL), creates tables; caller owns/closes.
- **`db.expr_exists(conn, expression) -> Optional[str]`** (db.py:149) — THE DEDUP HELPER (criterion 3). Returns existing `alpha_id` or `None`. Exact-string match, no normalization. Use this — do NOT hand-roll the SELECT.
- **`db.upsert_alpha(conn, alpha_dict) -> None`** (db.py:69) — INSERT OR REPLACE on `alpha_id`. `archetype` is a writable column (26 `_ALPHA_COLS`, db.py:46-52); missing keys default NULL.
- **`validate.validate(conn, expression) -> tuple[bool, str]`** (validate.py:23) — THE GATE (criterion 2). `(True,"")` if valid; else `(False, reason)`, fail-fast: empty → unbalanced parens → `unknown operator: {tok}` → `unknown data field: {tok}`. Requires operators/datafields synced. Numeric literals never flagged.
- **Grading handoff (Phase 2 does NOT call this — human runs it):** Path A = ideator writes a `seeds.txt`-format file (one FastExpr/line; blank lines and `#` ignored, cli.py:62-64) → `python cli.py <file> [--db PATH] [--sync] [--workers {1,2,3}]` (cli.py:26) does single-shot login + init_db + optional sync + `grade_many` (workers clamped ≤3, grade.py:228). `grade.grade_one` already calls `expr_exists` then `validate` internally before simulating.
- **Imports:** `researcher.py` → `import db`. `ideator.py` → `import db, validate`.
- **Constraints (CLAUDE.md):** single-shot `wq_login.login()`, never re-auth in-loop (429 lockout); ≤3 concurrent sims; `client.simulate(expr)` positional only (never `regular=`); never hardcode check limits.

## Citable past-alpha insights (for criterion 1)

`alphas`: 384 rows (363 UNSUBMITTED, 16 ACTIVE, 5 fail). **`archetype`, `self_corr`, `prod_corr` are NULL across all 384** — resolved correlations live ONLY in memory files. So thesis insight citations must use `sharpe`/`fitness`/`turnover`/`status` (from `alphas`) and check pass/fail (from `checks`); self_corr citations come from memory.

- **qMXnEVQK** (memory) — GARP analyst price-ratio; passes ALL IS checks, Sharpe 1.62/Fitness 1.79, self_corr 0.3455, SECTOR neut. The verified-submittable anchor.
- **e7rnMqwp** (memory) — qMXnEVQK + `winsorize(signal,std=4)` + INDUSTRY neut → Sharpe 1.82, self_corr 0.256. **Lesson: winsorize is the dominant self-corr-lowering lever AND lifts Sharpe; `rank(signal)` destroys magnitude; INDUSTRY/SUBINDUSTRY beat SECTOR.**
- **59-alpha clean pool**: UNSUBMITTED with Sharpe≥1.25 ∧ Fitness≥1.0 ∧ Turnover≤0.4 — a citable "diversify around this pool" hook (query `alphas` directly).
- **5 FAILURES (anti-pattern)**: all naive single-operator price/volume signals (`rank(ts_mean(returns,10))` etc.) — failing LOW_SHARPE (1.25), LOW_FITNESS (1.0), CONCENTRATED_WEIGHT (0.10), LOW_SUB_UNIVERSE_SHARPE. Winners use sentiment/fundamentals/analyst data.
- Most-reused profitable blocks: `vec_avg(nws12_afterhsz_sl)` (18×), `operating_income/{close,cap}` (17×), `winsorize` (5×), `debt_lt` (3×), GARP `mdl177_garpanalystmodel_qgp_vfpriceratio`.

## Archetype taxonomy (8 archetypes — full skeletons in 02-GROUNDING.md §Archetype taxonomy)

`reversal, momentum, value_garp, quality, growth, low_volatility, liquidity_volume, sentiment_event`. Each maps to grounded operator families + datafield categories + a pseudo-valid skeleton FastExpr. Steering: always wrap final signal in a cross-sectional normalizer (`rank`/`zscore`/`scale`); prefer INDUSTRY/SUBINDUSTRY neut; apply `winsorize(signal,std=4)` for self-corr control; reduce VECTOR fields with `vec_avg`. All skeletons must still pass `validate.validate` + `db.expr_exists` before grading.

## Obsidian thesis-note template (full template in 02-GROUNDING.md §Obsidian thesis-note template)

Vault `/Users/winter.__.kor/quant/alpha-kb/` (Theses/, Archetypes/, Failures/). Note: `Theses/YYYY-MM-DD-<archetype>-<slug>.md`. Frontmatter: title, date, status, archetype, run_id, region/universe/delay, `source_operators` (⊆ operators.name), `source_datafields` (⊆ datafields.id), `cited_alpha_ids`, `cited_insights`, `candidate_count`. Body: Thesis → Economic rationale → Grounding (operator/field tables) → Past-result insight cited → Candidate expressions (seeds.txt-format fenced block + table with dedup status) → Next steps.

## Lessons from reference tooling (popsukss, worldquant-miner)

Borrow: clean research→ideate loop ergonomics; mutate-verified-winners pattern (seed from the 59-pool / qMXnEVQK lineage). Avoid (their failure modes → our mitigation): hallucinated operators → validate against `operators.name`; hardcoded 10-field whitelist → read full synced `datafields`; random structure → grounded archetype skeletons; no pre-sim gate → mandatory `validate.validate` + `db.expr_exists`; cross-run duplicates → persistent `db.expr_exists`; hardcoded thresholds → read limits from BRAIN at grade time (Phase 1 already does).

## Proposed plan breakdown (4 plans)

1. **02-01 — `researcher.py` + insight queries.** Catalog SELECTs + past-alpha insight queries (sharpe/fitness/status, common FAIL checks, 59-pool); deterministic archetype selection (rotate under-explored / target clean pool); LLM thesis prose; emit grounded thesis Markdown. Touches: `db.init_db`, catalog SELECTs, `alphas`/`checks` reads.
2. **02-02 — `ideator.py` + archetype tagging + dedup.** Consume thesis; compose 4–8 FastExpr candidates from grounded archetype skeletons; gate each via `validate.validate`; dedup via `db.expr_exists`; inherit archetype tag from thesis frontmatter; output seeds.txt format. Touches: `validate.validate`, `db.expr_exists`, catalog SELECTs.
3. **02-03 — `/find-alphas` command + Obsidian emit + vault scaffold.** Orchestrate Researcher→Ideator; scaffold `alpha-kb/`; emit thesis note (frontmatter + body + seeds-format candidate block) to `Theses/`; write a `runs` row (run_id, notes path). STOPS for human review — no grading. Touches: orchestration, note template, `runs` write.
4. **02-04 — end-to-end checkpoint.** Run `/find-alphas` against live KB; verify all 3 success criteria (note cites real tokens + ≥1 SQLite insight; validator rejects zero outputs; every candidate archetype-tagged + `expr_exists`-confirmed absent). Optional manual smoke test handing a small batch to `python cli.py` (≤3 workers).

## Open items resolved
All 7 open questions from the brief are RESOLVED in 02-CONTEXT.md (LOCKED decisions). Honor them.
