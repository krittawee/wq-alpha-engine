# Phase 7: Brute-Force Tool (Tool B) — Research

**Researched:** 2026-06-15
**Domain:** In-repo combinatorial alpha enumeration pipeline (template → validate → probe → bulk-sim → additivity gate → persist)
**Confidence:** HIGH — all findings grounded in live code reads; no WebSearch required; this is an internal implementation problem with verified primitives.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Templates are in-repo Python data structures in `templates.py` — mirroring `delay0_candidates._D0_CANDIDATES` and `optimizer.ARCHETYPE_HEURISTICS`. No YAML/JSON, no CLI-only definition.
- **D-02:** Ship all 4 ACE-inspired shapes pre-loaded: sentiment, fundamental, residual, beta.
- **D-03:** A template field slot can declare a catalog filter (`dataset=`, `type=`) that auto-expands to all matching synced fields, OR list literals. Catalog-query is the default. `validate.py` gates every combo regardless.
- **D-04:** Settings slots (neutralization, decay, truncation) are enumerated alongside expression slots. Reuse `optimizer.py` variant logic as a library for the settings grid. Full enumeration = cartesian product of expression-slots x settings-slots.
- **D-05:** Template kept if >=1 probe sample sim is clean (no BRAIN ERROR) AND reaches at least NEAR. Abandoned only when every probe errors or is far FAIL. Log: "template abandoned after probe".
- **D-06:** Probe sample spreads across slot values (cover every distinct slot value at least once). Default size 5, configurable via `--probe-size`.
- **D-07:** Quota counted in additive survivors (pass all IS checks AND clear additivity gate). Default 5, configurable via `--quota`. IS-pass-but-correlated does NOT count.
- **D-08:** Defaults to delay-0 (`--delay 0`). Overridable via `--delay 1`. Uses Phase-5 `--delay` plumbing.
- **D-09:** Templates processed sequentially. Run stops on: quota met, 401 session expiry, or dry. On 401 → persist partial progress and report. Never re-auth in-loop.
- **D-10:** Survivors persisted as full rows in existing `alphas` + `checks` tables. Failures stored as per-(run, template) aggregates (not one row per dead combo).
- **D-11:** New `bruteforce_runs` table for per-template failure aggregates + run params. Existing `runs` table gets one row per `/bruteforce` invocation.

### Claude's Discretion

- Execution mechanics for "quota-met stops mid-flight at ≤3 concurrent" — whether to reuse `grade.grade_many` as-is or add a streaming/quota-aware scheduler variant.
- Exact `bruteforce_runs` column types/indexes and CLI flag set.
- 401-detection mechanism (where in the grade path 401 surfaces).
- Numeric definition of "far FAIL" for probe-abandon (must reuse `editor.classify_from_checks` NEAR/FAIL vocabulary).

### Deferred Ideas (OUT OF SCOPE)

- Shared sim-queue for true Tool A+B simultaneity (v1.2).
- LLM learning/memory loop distilling brute-force survivors + failure-reasons (v1.2).
- `/hunt` evolution and `/find-alphas` fold (Phase 8).
- `/iterate` decorrelate mode (Phase 9).
- Auto-submit.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BF-01 | User can define a parameterized template (operator/field/window slots); system enumerates valid combinations | templates.py data structure design (D-01/D-02/D-03/D-04); catalog query via `datafields` table |
| BF-02 | Every enumerated combination is locally validated against the catalog before any simulation | `validate.validate(conn, expression)` — verify.py:23 — reused as-is; called on every combo |
| BF-03 | System probe-simulates a small sample and abandons template if sample shows no viable alpha | `grade.grade_one` for probe path; `editor.classify_from_checks` for NEAR/FAIL verdict (D-05/D-06) |
| BF-04 | Bulk-simulates surviving combinations at ≤3 concurrent, stopping on quota / 401 / dry | `grade.grade_many` reuse analysis — see Open Questions Q1; 401 propagation (Q2) |
| BF-05 | Runs standalone with no AI dependency, using only the cached BRAIN session | wq_login.py single-shot auth pattern; no LLM imports; AI-free constraint analysis |
| BF-06 | Records survivors + structured failure-reasons (not every raw combo) | `bruteforce_runs` table design (D-11); `alphas`/`checks` upsert for survivors |
</phase_requirements>

---

## Summary

Phase 7 adds a fully standalone, AI-free tool (`/bruteforce` command + `bruteforce.py` engine + `templates.py`) that discovers additive alphas by combinatorially enumerating parameterized templates. All core primitives already exist and are verified against live code: `validate.validate`, `grade.grade_one`/`grade_many`, `optimizer.build_variants`/`ARCHETYPE_HEURISTICS`, `additivity.rank_by_proxy`/`confirm_additive`, `editor.classify_from_checks`, `db.upsert_alpha`/`upsert_checks`, and the `runs`-table insert pattern. The only new code is `templates.py` (template shapes), `bruteforce.py` (orchestrator), the `bruteforce_runs` table migration in `db.py`, and the `bruteforce.md` command file.

The most important design finding for the planner: `grade.grade_many` as written is a **batch-all-then-return** function — it submits the full list to a `ThreadPoolExecutor` and blocks until every item finishes. This is incompatible with "stop mid-flight when quota is met." The recommended approach is to **not use `grade_many` for bulk-sim**; instead call `grade.grade_one` directly in a controlled loop that checks quota after each result, with `concurrent.futures.as_completed` for the ≤3 concurrent cap. The probe-sim path (5 items, sequential or 3-concurrent) can use `grade_many` as-is.

The 401 surfaces as `requests.exceptions.HTTPError` with `status_code == 401`, re-raised immediately from both `_simulate_to_alpha` (grade.py:93-94) and `grade_many`'s worker wrapper (grade.py:480-481). The catch in `bruteforce.py` is identical to the pattern in `cli.py` and `hunt.md`.

**Primary recommendation:** Build `bruteforce.py` as a sequential-template loop with an inner concurrent-batch scheduler (manual `ThreadPoolExecutor` + `as_completed` + quota check after each future resolves), not by extending `grade_many`. This is the minimal safe path that satisfies D-09 (stop cleanly on quota/401/dry) without modifying the tested grade primitives.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Template definition & enumeration | App layer (templates.py + bruteforce.py) | — | Pure in-repo Python; no BRAIN call |
| Local validation of each combo | App layer (validate.py) | SQLite catalog | Already exists; zero API cost |
| Catalog-grounded slot expansion | SQLite (datafields table) | — | Query `WHERE dataset=? AND type=?` on synced rows |
| Settings-grid generation | App layer (optimizer.py library) | — | `ARCHETYPE_HEURISTICS` reused as data source; `build_variants` signature requires alpha_row |
| Probe-sim (small sample) | BRAIN API via grade.grade_one | App layer classify | Sequential or 3-concurrent; up to 5 sims |
| Bulk-sim (quota-aware) | BRAIN API via grade.grade_one + manual scheduler | — | grade_many cannot stop mid-flight; custom loop needed |
| Additivity gate | additivity.py (proxy + confirm) | BRAIN /check | Reused exactly from Phase 6 |
| Survivor persistence | db.py (upsert_alpha + upsert_checks) | — | Existing path; survivors land in same tables |
| Failure aggregation | bruteforce_runs table (new) | SQLite | Per-(run,template) aggregates only |
| Auth & session | wq_login.py | grade.py 401 propagation | Single-shot; 401 stops run cleanly |

---

## Standard Stack

### Core (existing — all verified via code reads)

| Library/Module | Location | Purpose | Key Function |
|----------------|----------|---------|--------------|
| `validate` | validate.py:23 | Local catalog/syntax gate before any sim | `validate(conn, expression) -> (bool, reason)` |
| `grade` | grade.py:108, 404 | BRAIN-sim + IS-check primitives | `grade_one(client, conn, expr, run_id, settings, delay) -> dict`; `grade_many(...)-> list[dict]` |
| `optimizer` | optimizer.py:42, 94 | Settings-variant data and builder | `ARCHETYPE_HEURISTICS`, `build_variants(alpha_row, conn) -> list[dict]` |
| `additivity` | additivity.py:174, 260 | Phase-6 additivity gate (reused) | `rank_by_proxy(candidates, conn) -> list[AdditivityResult]`; `confirm_additive(client, alpha_id, conn) -> AdditivityResult` |
| `editor` | editor.py:45 | NEAR/FAIL/PASS classification for probe-abandon | `classify_from_checks(alpha_id, conn) -> (str, list[str])` |
| `db` | db.py | Schema, CRUD, `bruteforce_runs` DDL | `upsert_alpha`, `upsert_checks`, `init_db`, `expr_exists` |
| `selfcorr` | selfcorr.py | Book PnL reference for additivity | `get_book_pnl_paths(conn)`, `backfill_active_pnl(client, conn, db_path)` |
| `probe_delay` | probe_delay.py | Delay-0 feasibility probe (inherited from Phase 5) | `probe_and_gate(client, conn, requested_delay)` |
| `wq_login` | wq_login.py | Single-shot auth | `login() -> client` |

### New Files

| File | Purpose |
|------|---------|
| `templates.py` | Template data structures (4 ACE-inspired shapes); mirrors `delay0_candidates.py` pattern |
| `bruteforce.py` | Orchestrator engine (template loop, probe gate, bulk-sim scheduler, additivity gate, failure aggregate) |
| `.claude/commands/bruteforce.md` | Command file (mirrors `hunt.md` pattern) |

### Supporting (stdlib only — no new third-party packages)

| Module | Use |
|--------|-----|
| `concurrent.futures.ThreadPoolExecutor` | ≤3 concurrent sims in bulk-sim scheduler (already used in grade_many) |
| `concurrent.futures.as_completed` | Quota-aware stop after each future resolves |
| `itertools.product` | Cartesian product of expression-slots x settings-slots |
| `json` | failure_counts / examples column serialization for bruteforce_runs |
| `uuid` | run_id generation (matches hunt.py pattern) |
| `argparse` | CLI flags (--delay, --quota, --probe-size, --db, --templates) |
| `requests.exceptions.HTTPError` | 401 detection |

**No new pip packages.** [VERIFIED: codebase — all imports in grade.py, hunt.py, additivity.py are stdlib or project modules]

---

## Package Legitimacy Audit

> Not applicable. Phase 7 introduces zero new external packages. All dependencies are Python stdlib or existing project modules.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## Architecture Patterns

### System Architecture Diagram

```
/bruteforce (CLI)
       |
       v
wq_login.login()  [ONCE — auth]
       |
       v
backfill_active_pnl()  [pre-loop — builds book PnL cache]
       |
       v
probe_and_gate()  [delay-0 feasibility check — inherited Phase 5]
       |
       v
  [For each template in templates.py]
       |
       +---> templates.expand(template, conn)
       |         |  catalog query on datafields WHERE dataset/type match
       |         v
       |     enumerate combos (itertools.product of slots x settings grid)
       |         |
       |         v
       |     validate.validate() on every combo  [local, free]
       |         |
       |     +---+---- pass ----> probe sample (5 combos, spread across slot values)
       |     |                       |
       |     |            grade.grade_one() x5 [sequential or 3-concurrent]
       |     |                       |
       |     |            editor.classify_from_checks() per result
       |     |                       |
       |     |            >=1 NEAR? --YES--> bulk-sim survivors
       |     |                              |
       |     |            NO (all far FAIL/ERROR) --> abandon template
       |     |                              |
       |     |                    [Quota-aware scheduler loop]
       |     |                    ThreadPoolExecutor(max_workers=3) + as_completed
       |     |                    check quota after each future resolves
       |     |                              |
       |     |                    IS survivors ---> additivity gate
       |     |                              |
       |     |                    rank_by_proxy() + confirm_additive()
       |     |                              |
       |     |                    ADDITIVE? --YES--> upsert_alpha + upsert_checks
       |     |                                       quota_count += 1
       |     |                    NO --> failure aggregate
       |     |
       |     +---- fail ----> failure_counts["validate-dropped"] += 1
       |
       +---> upsert bruteforce_runs row (per template)
       |
  [Stop when: quota_count >= --quota, OR 401, OR no templates left]
       |
       v
  Report: templates done, quota count, stop reason, partial progress
```

### Recommended Project Structure

```
quant/
├── templates.py          # NEW — 4 ACE-inspired template shapes + slot expansion logic
├── bruteforce.py         # NEW — orchestrator engine
├── .claude/commands/
│   └── bruteforce.md     # NEW — command file (mirrors hunt.md)
├── db.py                 # MODIFIED — add bruteforce_runs DDL + CRUD
├── grade.py              # UNCHANGED — grade_one used directly
├── validate.py           # UNCHANGED — reused as-is
├── optimizer.py          # UNCHANGED — ARCHETYPE_HEURISTICS + build_variants used as library
├── additivity.py         # UNCHANGED — reused as-is
├── editor.py             # UNCHANGED — classify_from_checks reused for probe verdict
```

---

## Open Questions Resolved

These were explicitly marked "Claude's Discretion" in CONTEXT.md. All resolved via live code reads.

### Q1: Quota-aware scheduler — can grade_many be reused as-is?

**Short answer: No. Use `grade.grade_one` directly in a manual `ThreadPoolExecutor` + `as_completed` loop.**

**Evidence (grade.py:489-491):**
```python
with ThreadPoolExecutor(max_workers=max_workers) as pool:
    # pool.map preserves input order, matching the sequential path.
    results = list(pool.map(_grade_isolated, pairs))
```
`pool.map(...)` is a **blocking** call that submits all items and blocks until all complete. There is no mechanism to cancel mid-pool or check quota after each result. `grade_many` returns a complete `list[dict]` — all results or nothing.

**Recommended approach:** For bulk-sim, implement a `_bulk_sim_quota_aware` helper in `bruteforce.py` that:
1. Opens its own `ThreadPoolExecutor(max_workers=3)`.
2. Submits futures individually via `executor.submit(grade._grade_isolated, ...)` or wraps `grade.grade_one` directly.
3. Uses `concurrent.futures.as_completed(futures)` to retrieve results one-by-one as they finish.
4. After each result, checks `if quota_count >= quota_limit: break` and calls `executor.shutdown(wait=False)` to abandon in-flight futures without waiting.
5. Re-raises any `requests.exceptions.HTTPError` with status 401 immediately (same pattern as grade_many:480-481).

For the **probe-sim** (5 items), `grade.grade_many(max_workers=3, ...)` can be reused as-is because the probe always grades a small, bounded sample and always finishes before the quota check is relevant.

**Note:** `grade._grade_isolated` is a nested function inside `grade_many` — it cannot be imported directly. The bruteforce scheduler should inline the same pattern: open a per-worker `db.init_db(db_path)` connection, call `grade.grade_one(client, worker_conn, expr, run_id, settings=s, delay=delay)`, catch non-401 exceptions as `{"status": "error"}`, and close the connection in a `finally` block. This is a 20-line wrapper that avoids touching grade.py.

### Q2: 401 detection — where exactly does it surface?

**Evidence:**

`grade.py:93-94` in `_simulate_to_alpha`:
```python
except requests.exceptions.HTTPError as e:
    if getattr(getattr(e, "response", None), "status_code", None) == 401:
        raise  # auth expired — abort the whole run, never re-auth
```

`grade.py:459-461` in `grade_many` sequential path:
```python
except requests.exceptions.HTTPError as e:
    if getattr(getattr(e, "response", None), "status_code", None) == 401:
        raise  # auth expired — abort the whole run
```

`grade.py:478-481` in `grade_many` concurrent worker:
```python
except requests.exceptions.HTTPError as e:
    if getattr(getattr(e, "response", None), "status_code", None) == 401:
        raise
```

Additionally, `poll_correlation` (grade.py:562) calls `r.raise_for_status()` — a 401 from `/check` polling also surfaces here.

**How bruteforce.py catches it:** Wrap the entire template loop in a top-level `try/except requests.exceptions.HTTPError` (same pattern as `cli.py:100-112` and the `hunt.md` example). On 401: call `_persist_partial_progress(conn, run_summary)`, print the partial progress report, and `sys.exit(1)`. The run is never re-authenticated.

**Persistence on 401:** At the moment the 401 propagates, all futures that completed before the break already wrote their rows to `alphas`/`checks` via `db.upsert_alpha` inside the worker connection. SQLite WAL mode ensures those writes are committed. The `bruteforce_runs` row for the in-progress template can be written with `partial=True` and the accumulated failure counts before exit.

### Q3: Catalog-grounded slot expansion — how to query synced fields (D-03)

**Evidence (db.py:36-37, sync.py:122-135):**

The `datafields` table schema:
```sql
CREATE TABLE IF NOT EXISTS datafields (
  id TEXT, description TEXT, dataset TEXT, region TEXT,
  universe TEXT, delay INTEGER, type TEXT,
  PRIMARY KEY (id, region, universe, delay, dataset)
)
```

Fields are stored with `dataset` (e.g., `"fundamental6"`, `"nws12"`) and `type` (e.g., `"MATRIX"`, `"VECTOR"`, `"DOUBLE"`). The `sync.py` sync path preserves both from BRAIN's `/data-fields` response.

**Slot expansion query pattern for templates.py:**
```python
def expand_field_slot(conn, dataset=None, type_=None, literals=None):
    """Return list of field id strings matching the slot filter."""
    if literals is not None:
        return literals  # curated set — skip catalog query
    params, clauses = [], []
    if dataset:
        clauses.append("dataset=?"); params.append(dataset)
    if type_:
        clauses.append("type=?"); params.append(type_)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT DISTINCT id FROM datafields {where}", params
    ).fetchall()
    return [r[0] for r in rows]
```

**One important pitfall:** The `datafields` table has a composite primary key `(id, region, universe, delay, dataset)`, meaning the same field `id` may appear multiple times for different (region, universe, delay) combos. Use `SELECT DISTINCT id` to avoid inflating the slot expansion. [VERIFIED: db.py:35-37]

**For delay-0 templates:** Filter with `delay=0` in the slot expansion query to restrict to fields that BRAIN has synced as available at delay-0. This automatically excludes fields that only work at delay-1. [VERIFIED: sync.py:83 — `delay` is a sync parameter passed to `/data-fields`]

### Q4: Settings grid via optimizer (D-04) — what does build_variants actually take and return?

**Evidence (optimizer.py:94-153):**

```python
def build_variants(alpha_row: dict, conn: sqlite3.Connection) -> list:
    """Return ≤4 settings dicts for the given NEAR alpha."""
```

`alpha_row` is a dict with keys: `alpha_id`, `archetype`, `decay`, `neutralization`, `truncation`. It is used to:
1. Look up the archetype heuristic list from `ARCHETYPE_HEURISTICS`.
2. Exclude the alpha's current `(decay, neutralization, truncation)` combo from variants.
3. Query `alphas` table for past PASS settings to fill remaining slots.

**Can it be called as a library for settings grid generation?** Partially. The archetype-lookup and heuristic-combo logic is reusable, but `build_variants` is designed around an *existing alpha row* — it deduplicates against the alpha's current settings and queries past PASS rows from DB.

**Recommended approach for bruteforce.py:** Do not call `build_variants` directly. Instead, consume `ARCHETYPE_HEURISTICS` as a data source:
```python
from optimizer import ARCHETYPE_HEURISTICS

def settings_grid_for_archetype(archetype: str) -> list[dict]:
    """Return list of full settings dicts from ARCHETYPE_HEURISTICS."""
    combos = ARCHETYPE_HEURISTICS.get(archetype, ARCHETYPE_HEURISTICS["reversal"])
    result = []
    for decay, neutralization, truncation in combos:
        s = dict(grade._BASE_SETTINGS)
        s["decay"] = decay
        s["neutralization"] = neutralization
        s["truncation"] = truncation
        result.append(s)
    return result
```

This avoids the alpha_row dependency while reusing the heuristic data that `build_variants` already uses. Templates that declare explicit settings slots override or extend this list; templates without settings slots get the full archetype grid.

**Cartesian product:** `itertools.product(expression_combos, settings_variants)` gives the full enumeration. A template with 50 expression combos and 4 settings variants = 200 total combos. All 200 pass through `validate.validate()` before any sim.

### Q5: bruteforce_runs schema (D-11) — mirror of db.py patterns

**Evidence (db.py:38-55, 68-97):**

Existing `runs` table:
```sql
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, thesis TEXT, started_at TEXT,
  iterations INTEGER, num_pass INTEGER, notes TEXT
)
```

`init_db` applies all DDL from the `_DDL` list. Idempotent migrations use `ALTER TABLE ... ADD COLUMN` wrapped in `try/except sqlite3.OperationalError`.

**Recommended `bruteforce_runs` DDL** (add to `_DDL` list in db.py):
```sql
CREATE TABLE IF NOT EXISTS bruteforce_runs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id       TEXT NOT NULL,                    -- FK to runs.run_id
  template_name TEXT NOT NULL,                   -- e.g. "sentiment_rank"
  delay        INTEGER,
  quota_target INTEGER,
  n_combos     INTEGER,                          -- total enumerated combos
  n_validated  INTEGER,                          -- passed validate.validate
  n_probed     INTEGER,                          -- simmed in probe phase
  n_simmed     INTEGER,                          -- simmed in bulk phase
  n_survivors  INTEGER,                          -- passed IS checks
  n_additive   INTEGER,                          -- passed additivity gate
  quota_hit    INTEGER DEFAULT 0,                -- 1 if this template completed the quota
  partial      INTEGER DEFAULT 0,                -- 1 if interrupted by 401
  failure_counts TEXT,                           -- JSON: {class: count}
  examples     TEXT,                             -- JSON: {class: [expr, ...]}
  started_at   TEXT,
  finished_at  TEXT
)
```
```sql
CREATE INDEX IF NOT EXISTS idx_bruteforce_runs_run ON bruteforce_runs(run_id)
```

**CRUD pattern** (mirrors `db.py` upsert functions):
```python
def insert_bruteforce_run(conn, row: dict) -> int:
    cols = [c for c in row]
    placeholders = ", ".join("?" for _ in cols)
    col_list = ", ".join(cols)
    cur = conn.execute(
        f"INSERT INTO bruteforce_runs ({col_list}) VALUES ({placeholders})",
        tuple(row[c] for c in cols),
    )
    conn.commit()
    return cur.lastrowid

def update_bruteforce_run(conn, rowid: int, updates: dict) -> None:
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn.execute(
        f"UPDATE bruteforce_runs SET {set_clause} WHERE id=?",
        (*updates.values(), rowid),
    )
    conn.commit()
```

**`failure_counts` JSON schema:**
```json
{
  "validate_dropped": 42,
  "sim_error": 3,
  "IS_fail_SHARPE": 8,
  "IS_fail_TURNOVER": 2,
  "gate_fail_correlated": 5,
  "probe_abandoned": 0
}
```
**`examples` JSON schema:**
```json
{
  "validate_dropped": ["rank(unknown_field)", "..."],
  "IS_fail_SHARPE": ["rank(close/open)", "..."]
}
```
Max 3 examples per class to avoid bloat.

### Q6: Probe-spread sampling (D-06) — slot data structures

**Design:** Each template defines a list of slots (each slot is a list of candidate values). After slot expansion via catalog query, the probe sample must cover every distinct slot value at least once, up to `--probe-size` (default 5).

**Algorithm:**
```python
def probe_spread_sample(combos: list[tuple], slots: list[list], size: int = 5) -> list[tuple]:
    """
    combos: list of (slot_val_0, slot_val_1, ..., settings_dict) tuples
    slots: list of slot value lists (to know unique values per slot)
    size: max sample size
    Returns: subset of combos that covers every distinct slot value at least once.
    """
    # Stage 1: greedy cover — pick combos until every slot value appears at least once
    covered = [set() for _ in slots]
    all_values = [set(s) for s in slots]
    selected, remaining = [], list(combos)
    for combo in combos:
        if len(selected) >= size:
            break
        useful = any(combo[i] not in covered[i] for i in range(len(slots)))
        if useful:
            selected.append(combo)
            for i in range(len(slots)):
                covered[i].add(combo[i])
    # Stage 2: fill remaining slots up to size with first remaining combos
    remaining_after = [c for c in combos if c not in selected]
    while len(selected) < size and remaining_after:
        selected.append(remaining_after.pop(0))
    return selected
```
This is an internal function in `bruteforce.py` — no external dependency.

### Q7: Survivor persistence (D-10) — upsert paths confirmed

**Evidence (db.py:100-109, db.py:112-135):**

`db.upsert_alpha(conn, alpha_dict)` uses `INSERT OR REPLACE` with all `_ALPHA_COLS`. `db.upsert_checks(conn, alpha_id, checks_list)` uses `INSERT OR REPLACE` on `(alpha_id, name)`. Both are already called by `grade.grade_one` for every graded expression — survivor rows are already present in `alphas`/`checks` when the additivity gate runs.

**For survivors:** No additional DB write needed for the alpha itself. The additivity gate calls `additivity.confirm_additive(client, alpha_id, conn)` which calls `grade.trigger_correlation_check` + `grade.poll_correlation` and returns an `AdditivityResult`. The correlation check result is persisted by `grade.grade_one`'s Phase B path — but since probe-sim survivors are graded via `grade.grade_one`, their Phase B (`trigger_correlation_check` + `poll_correlation`) runs as part of grading.

**Important:** In `grade.grade_one`, Phase B (correlation check) runs automatically when `is_survivor=True`. So by the time bruteforce.py calls `additivity.rank_by_proxy`, each IS-passing alpha already has `pnl_path` populated (set in grade_one via `selfcorr.fetch_and_cache_pnl`) and its correlation check triggered. The additivity gate only needs to call `confirm_additive` for finalists — it does not need to trigger a fresh correlation check.

**Additivity gate wiring** mirrors `hunt._apply_additivity_gate` (hunt.py:86-165) exactly. Build `pass_candidates = [{"alpha_id": aid, "pnl_path": row[0]} for aid, row in ...]`, call `rank_by_proxy`, filter `proxy_drop` and `skipped`, call `confirm_additive` on top-CONFIRM_LIMIT survivors. Additive ones increment `quota_count`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Local expression validation | Custom token parser | `validate.validate(conn, expression)` — validate.py:23 | Already handles operator tokens, bracket balance, field tokens, named-arg exclusion, variable assignment exclusion |
| BRAIN sim + IS check extraction | Direct `client.simulate()` calls | `grade.grade_one(client, conn, expr, run_id, settings, delay)` — grade.py:108 | Handles retry/backoff, 401 propagation, coercion detection, settings recording, upsert |
| PASS/NEAR/FAIL classification | Gap arithmetic | `editor.classify_from_checks(alpha_id, conn)` — editor.py:45 | Handles hard-fail checks, 20% margin NEAR rule, PENDING exclusion |
| Additivity ranking | PnL correlation math | `additivity.rank_by_proxy(candidates, conn)` — additivity.py:174 | Combined-book corr + max-pairwise + proxy-drop logic all in one call |
| Additivity confirmation | `/check` polling | `additivity.confirm_additive(client, alpha_id, conn)` — additivity.py:260 | BRAIN-sourced limits, PROD_CORRELATION absence handling, timeout graceful degrade |
| Settings variant generation | Hardcoded neutralization list | `optimizer.ARCHETYPE_HEURISTICS` — optimizer.py:42 | 8 archetype x 4 combos of (decay, neutralization, truncation) already validated against PASS outcomes |
| Delay feasibility check | Direct sim + manual delay compare | `probe_delay.probe_and_gate(client, conn, requested_delay)` — probe_delay.py | Raises `DelayCoercedError` on coercion; reuses `_simulate_to_alpha` retry logic |
| SQLite concurrent writes | Lock management | `db.init_db(path)` in each worker thread — db.py:68 | WAL + busy_timeout=30000 already configured; each worker opens its own connection |
| Cartesian product enumeration | Nested for-loops | `itertools.product(*slot_lists)` | Stdlib; handles arbitrary slot counts cleanly |

---

## Common Pitfalls

### Pitfall 1: Calling grade_many for bulk-sim and expecting quota-stop
**What goes wrong:** `grade_many` with `max_workers=3` uses `pool.map(...)` which blocks until ALL submitted expressions finish. If you submit 100 combos and quota=5, the pool runs all 100 sims before you can check quota.
**Why it happens:** `pool.map` is a blocking batch operation (grade.py:489-491). There is no hook to interrupt it.
**How to avoid:** Use `ThreadPoolExecutor(max_workers=3)` + `executor.submit()` + `as_completed()` in bruteforce.py's bulk-sim loop. Check quota after each `future.result()` call.
**Warning signs:** If you see all 100 combos graded when you set quota=5, grade_many was used for bulk-sim.

### Pitfall 2: Using grade_many's internal `_grade_isolated` — it's not importable
**What goes wrong:** `_grade_isolated` is a nested function defined inside `grade_many`. It is not accessible via `grade._grade_isolated`.
**How to avoid:** Inline the same pattern (per-worker `db.init_db`, call `grade.grade_one`, catch non-401 exceptions, close connection in `finally`).

### Pitfall 3: VECTOR-type fields used without vec_avg
**What goes wrong:** Fields with `type='VECTOR'` (e.g., `nws12_afterhsz_sl`) are multi-column and must be wrapped in `vec_avg(...)` or similar aggregator. Raw use fails BRAIN validation.
**Why it happens:** The catalog doesn't enforce this — `validate.validate` passes the field name as valid, but the sim errors.
**How to avoid:** In `templates.py`, wrap VECTOR slot values explicitly in `vec_avg(...)`. The template definition layer — not the slot expansion — must handle this. Alternatively, filter VECTOR type out of catalog-expanded slots unless the template explicitly requests them.

### Pitfall 4: Same field ID appearing multiple times in slot expansion
**What goes wrong:** `datafields` has composite PK `(id, region, universe, delay, dataset)`. A bare `SELECT id FROM datafields WHERE dataset=?` returns duplicates for multi-region syncs.
**How to avoid:** Always use `SELECT DISTINCT id FROM datafields WHERE ...` in the slot expansion query.

### Pitfall 5: Skipping validate on settings-slot combos
**What goes wrong:** Adding a new `(decay, neutralization, truncation)` combo doesn't change the expression — validate.py would pass it trivially. But if the expression changes when settings change (expression templates that reference settings-parameterized sub-expressions), each new (expression, settings) combo must still be validated.
**How to avoid:** Always run `validate.validate(conn, expression)` for the expression component of every (expression, settings) combo, regardless of which slot generated it.

### Pitfall 6: Probe-sim writing permanent rows that interfere with bulk-sim dedup
**What goes wrong:** `grade.grade_one` calls `db.upsert_alpha` for every completed sim. Probe sims produce rows in `alphas`. When bulk-sim then tries the same expression, `grade.grade_one`'s dedup logic (grade.py:165-177) may skip it as a duplicate if the delay and expression match.
**Why this is actually fine:** The probe sims already produce fully graded rows. The bulk-sim just skips them cleanly via the duplicate path. No data is lost. The probe results should be counted as "n_probed" not duplicated in "n_simmed."
**Warning sign to watch:** If probe results land as "duplicate" in bulk-sim, check whether `delay` is being passed correctly through both calls.

### Pitfall 7: Additivity gate called before pnl_path is populated
**What goes wrong:** `additivity.rank_by_proxy` checks `pnl_path` for each candidate. If `grade.grade_one`'s Phase B (selfcorr.fetch_and_cache_pnl) failed silently, `pnl_path` is NULL and the candidate is appended as `skipped=True`.
**Why it happens:** `selfcorr.fetch_and_cache_pnl` returns `None` on any HTTP error — graceful degrade (grade.py:333). Missing PnL does not abort grading.
**How to avoid:** Log `skipped=True` candidates in the failure aggregate. They may still be confirmed additive via `confirm_additive` (which does not require local PnL). Do not skip them from the gate — let rank_by_proxy's fallback path handle them.

### Pitfall 8: 401 during additivity gate leaving partial DB state
**What goes wrong:** `confirm_additive` calls `grade.trigger_correlation_check` and `grade.poll_correlation`, both of which raise on 401. If the 401 happens mid-gate, some candidates may have had their correlation check triggered but not resolved.
**How to avoid:** Wrap the entire additivity gate block in the same `try/except HTTPError` as the main loop. On 401, the correlation check result is not yet written to DB (it's only written in `grade_one`'s Phase B). The alpha row is still `status='pass'` in DB — correct. The failure aggregate for that template should record `partial=True`.

---

## Code Examples

Verified patterns from live code reads:

### Template data structure (mirrors delay0_candidates._D0_CANDIDATES and optimizer.ARCHETYPE_HEURISTICS)
```python
# templates.py — mirroring delay0_candidates.py:48 and optimizer.py:42 pattern
# [VERIFIED: delay0_candidates.py:48, optimizer.py:42]

TEMPLATES = [
    {
        "name": "sentiment_rank",
        "archetype": "sentiment_event",
        "description": "Rank of sentiment signal over a window",
        "slots": {
            "field": {"dataset": "nws12", "type": "VECTOR"},  # catalog-expanded; wrap in vec_avg
            "window": [5, 10, 20],                             # literal list
        },
        "expression": "rank(ts_sum(vec_avg({field}), {window}))",  # {slot} placeholders
        "settings_archetype": "sentiment_event",  # key into ARCHETYPE_HEURISTICS
    },
    # ... fundamental, residual, beta shapes
]
```

### Catalog-grounded slot expansion
```python
# [VERIFIED: db.py:36-37, sync.py:122-135]
def expand_slot(conn, slot_def):
    if isinstance(slot_def, list):
        return slot_def  # literal
    dataset = slot_def.get("dataset")
    type_ = slot_def.get("type")
    clauses, params = [], []
    if dataset:
        clauses.append("dataset=?"); params.append(dataset)
    if type_:
        clauses.append("type=?"); params.append(type_)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        f"SELECT DISTINCT id FROM datafields {where}", params
    ).fetchall()
    return [r[0] for r in rows]
```

### grade_one signature (probe and bulk-sim calls)
```python
# [VERIFIED: grade.py:108-142]
result = grade.grade_one(
    client=client,
    conn=conn,           # worker's own connection (from db.init_db(db_path))
    expression=expr,
    run_id=run_id,
    settings=settings_dict,   # full settings dict including delay
    delay=delay,              # 0 or 1
)
# result["status"] in ("pass", "fail", "duplicate", "invalid", "error", "coerced", "timeout")
# result["alpha_id"] — BRAIN alpha_id or None
# result["checks"] — raw is.checks list
```

### classify_from_checks for probe-abandon (D-05)
```python
# [VERIFIED: editor.py:45-95]
# "far FAIL" = classify_from_checks returns 'fail' (not 'near' or 'pass')
status, failing_checks = editor.classify_from_checks(probe_alpha_id, conn)
# status in ('pass', 'near', 'fail', 'unknown')
# Template kept if ANY probe_status in ('pass', 'near')
# Template abandoned if ALL probe statuses in ('fail', 'unknown') or sim 'error'
```

### Additivity gate wiring (mirrors hunt._apply_additivity_gate)
```python
# [VERIFIED: hunt.py:86-165, additivity.py:174, 260]
pass_candidates = [
    {"alpha_id": aid, "pnl_path": conn.execute(
        "SELECT pnl_path FROM alphas WHERE alpha_id=?", (aid,)
    ).fetchone()[0]}
    for aid in is_pass_ids
]
ranked = additivity.rank_by_proxy(pass_candidates, conn)
survivors = [r for r in ranked if not r.proxy_drop]
for r in survivors[:additivity.CONFIRM_LIMIT]:
    result = additivity.confirm_additive(client, r.alpha_id, conn)
    if result.additive is True:
        quota_count += 1
        additive_ids.append(r.alpha_id)
```

### bruteforce_runs row insert (D-11)
```python
# [VERIFIED: db.py:68-97 pattern]
run_row = {
    "run_id": run_id,
    "template_name": template["name"],
    "delay": delay,
    "quota_target": quota,
    "n_combos": n_combos,
    "n_validated": n_validated,
    "n_probed": n_probed,
    "n_simmed": n_simmed,
    "n_survivors": n_survivors,
    "n_additive": n_additive,
    "quota_hit": int(quota_count >= quota),
    "partial": 0,
    "failure_counts": json.dumps(failure_counts),
    "examples": json.dumps(examples),
    "started_at": started_at,
    "finished_at": datetime.utcnow().isoformat(),
}
db.insert_bruteforce_run(conn, run_row)
```

### 401 catch pattern (mirrors cli.py:100-112 and hunt.md)
```python
# [VERIFIED: cli.py:100-112, grade.py:93-94, 459-461, 478-481]
import requests, sys
try:
    result = bruteforce_engine(client, conn, ...)
except requests.exceptions.HTTPError as e:
    if getattr(getattr(e, "response", None), "status_code", None) == 401:
        _persist_partial_progress(conn, run_id, partial_summary)
        print("[bruteforce] AUTH EXPIRED — 401. Re-run /bruteforce to re-authenticate.")
        print(f"  Templates completed: {n_templates_done}")
        print(f"  Additive survivors found: {quota_count}/{quota}")
        sys.exit(1)
    raise
```

### runs table insert (mirrors hunt.py pattern)
```python
# [VERIFIED: hunt.py:245-249, db.py:38-41]
conn.execute(
    "INSERT OR IGNORE INTO runs (run_id, thesis, started_at, iterations, num_pass) "
    "VALUES (?, ?, ?, ?, ?)",
    (run_id, f"bruteforce delay={delay} quota={quota}", datetime.now(timezone.utc).isoformat(), 0, 0),
)
conn.commit()
# Update at end:
conn.execute(
    "UPDATE runs SET iterations=?, num_pass=? WHERE run_id=?",
    (n_simmed, quota_count, run_id),
)
conn.commit()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hunt only (AI-driven, sim-light) | Two tools: Hunt (AI) + Bruteforce (AI-free, sim-heavy) | Design doc 2026-06-11 | Bruteforce runs when AI quota exhausted |
| Additivity check = not yet wired | Phase-6 gate: rank_by_proxy + confirm_additive | Phase 6, 2026-06-15 | Survivors must be additive, not just IS-passing |
| Delay hardcoded to 1 | `--delay` flag threaded end-to-end | Phase 5, 2026-06-13 | Delay-0 alphas structurally decorrelated from book |
| grade.py recorded requested settings | grade.py records BRAIN's returned settings | 2026-06-11 fix | Coercion detected; mislabeled rows prevented |
| `regular=` param to simulate() | Never pass `regular=`; expression is 1st positional arg only | CLAUDE.md | Prevents silent expression drop bug |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | VECTOR-type fields (e.g., nws12) must be wrapped in `vec_avg` in template expressions | Pitfall 3, templates.py design | BRAIN sim ERROR on VECTOR fields used raw; probe-sim would catch this but wastes a sim slot |
| A2 | `datafields.dataset` values like `"nws12"`, `"fundamental6"` match what BRAIN returns in the `/data-fields` response and are synced verbatim by sync.py | Q3 slot expansion | Slot filter `dataset='nws12'` returns zero rows if BRAIN uses a different dataset ID string |
| A3 | `additivity.CONFIRM_LIMIT` (currently 3) is the right cap for bruteforce; the gate is called once per /bruteforce run (not once per template) | Q7, additivity gate wiring | If called once per template, BRAIN /check budget explodes for long runs |

**Note on A3:** The recommended wiring (consistent with `hunt._apply_additivity_gate`) is to collect all IS-passing alpha_ids across all templates, then run the gate once at the end (or per template with a shared quota counter). This matches the design doc's "collect the additive ones" flow.

---

## Open Questions

1. **ACE template shapes — exact expression structure**
   - What we know: The 4 shapes are sentiment, fundamental, residual, beta. ACE repo `JediNakDev/wq-alpha-sim` has the shapes but is NOT to be cloned/imported.
   - What's unclear: The exact FastExpr template strings for each shape (operator choices, window ranges) — these need to be authored for templates.py in Phase 7.
   - Recommendation: The planner should define the 4 template expressions as the first task (Plan 07-01: templates.py), using fields from `CLAIMED_DELAY0_FIELDS` (delay0_candidates.py) for delay-0 mode and `ARCHETYPE_HEURISTICS["sentiment_event"]` / `["value_garp"]` etc. for settings archetype hints. The templates should be concrete enough to actually run, not placeholder stubs.

2. **Where to run the additivity gate — per-template or end-of-run**
   - What we know: hunt.py runs it once at end-of-run over all PASS ids.
   - What's unclear: For bruteforce, running per-template means quota_count can stop the run after the first additive template. Running end-of-run means we might sim more than needed.
   - Recommendation: Run per-template, immediately after bulk-sim survivors are collected. This enables the "stop on quota met" condition (D-07) during the template loop.

3. **`--probe-size` vs `--probe-sample-size` naming**
   - Minor. D-06 says `--probe-size`; align with that name.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.x | All | Yes (project already running) | — | — |
| SQLite (alpha_kb.db) | validate, grade, db, additivity | Yes (2.8M DB present) | — | — |
| BRAIN session (wq_login) | grade_one, confirm_additive | Yes (single-shot auth) | — | 401 stops run, user re-auths |
| `concurrent.futures` | bulk-sim scheduler | Yes (stdlib) | — | — |
| `itertools` | cartesian product | Yes (stdlib) | — | — |

**Missing dependencies with no fallback:** None — Phase 7 has no external dependencies beyond the existing project stack.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Python unittest / pytest (project uses both; test_phase*.py files exist) |
| Config file | none — tests run directly |
| Quick run command | `python -m pytest test_phase7.py -x -q` |
| Full suite command | `python -m pytest test_phase7.py -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BF-01 | Template enumeration produces expected combos | unit | `pytest test_phase7.py::test_template_enumeration -x` | No — Wave 0 |
| BF-01 | Catalog slot expansion returns only fields matching filter | unit | `pytest test_phase7.py::test_slot_expansion -x` | No — Wave 0 |
| BF-02 | validate.validate called on every enumerated combo | unit (mock validate) | `pytest test_phase7.py::test_validate_gate -x` | No — Wave 0 |
| BF-03 | Probe sample covers all distinct slot values | unit | `pytest test_phase7.py::test_probe_spread_sample -x` | No — Wave 0 |
| BF-03 | Template abandoned when all probes are far FAIL | unit (mock grade_one) | `pytest test_phase7.py::test_probe_abandon -x` | No — Wave 0 |
| BF-04 | Bulk-sim stops on quota met without grading remaining combos | unit (mock grade_one) | `pytest test_phase7.py::test_quota_stop -x` | No — Wave 0 |
| BF-04 | 401 stops run cleanly, persists partial progress | unit (mock HTTPError) | `pytest test_phase7.py::test_401_stop -x` | No — Wave 0 |
| BF-05 | No LLM import in bruteforce.py or templates.py | static check | `grep -r "claude\|anthropic\|llm" bruteforce.py templates.py` | No — Wave 0 |
| BF-06 | bruteforce_runs row written per template | unit (SQLite in-memory) | `pytest test_phase7.py::test_bruteforce_runs_schema -x` | No — Wave 0 |
| BF-06 | Survivors land in alphas table visible to additivity gate | integration (mock BRAIN) | `pytest test_phase7.py::test_survivor_persistence -x` | No — Wave 0 |

### Wave 0 Gaps

- `test_phase7.py` — does not exist; must be created in Wave 0 (Plan 07-01 or dedicated test-setup plan)
- Fixtures: `mock_grade_one` (returns canned result dict), `mock_classify_from_checks`, `mock_confirm_additive`, in-memory SQLite with `db.init_db(":memory:")`

### Sampling Rate

- Per task commit: `python -m pytest test_phase7.py -x -q`
- Per wave merge: `python -m pytest test_phase7.py -v`
- Phase gate: full test_phase7.py green before `/gsd:verify-work`

---

## Security Domain

> `security_enforcement` not explicitly set to false in `.planning/config.json`. Section included.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Yes (BRAIN session) | Single-shot auth only; 401 stops run; never re-auth in-loop |
| V3 Session Management | No | No web session; BRAIN client is a `requests.Session` object |
| V4 Access Control | No | No multi-user; single-user CLI tool |
| V5 Input Validation | Yes (template expressions) | `validate.validate(conn, expression)` gates every combo before BRAIN call |
| V6 Cryptography | No | No crypto operations in this phase |

### Known Threat Patterns for BRAIN API + CLI tool

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Template expression with injected malicious field token | Tampering | `validate.validate` rejects all unknown tokens against synced catalog |
| Auth session reuse after expiry | Elevation of Privilege | 401 stops run cleanly; never re-auth; user controls re-auth |
| DB write concurrency corruption | Tampering | SQLite WAL + busy_timeout=30000 (db.py:79); each worker opens own connection |
| Biometric throttle from repeated auth | Denial of Service | Single-shot auth pattern enforced in bruteforce.md command; never re-auth |
| SQL injection via template field values | Tampering | All DB queries use parameterized statements (verified in validate.py:87-91, db.py) |

---

## Sources

### Primary (HIGH confidence — verified against live code in this session)

- `grade.py` (lines 63-105, 108-401, 404-504, 512-585) — `_simulate_to_alpha`, `grade_one`, `grade_many`, `trigger_correlation_check`, `poll_correlation`; 401 propagation paths
- `optimizer.py` (lines 42-153) — `ARCHETYPE_HEURISTICS` data structure; `build_variants` signature and logic
- `additivity.py` (lines 1-50, 174-353, 260-380) — `rank_by_proxy`, `confirm_additive` signatures and return types
- `editor.py` (lines 45-95) — `classify_from_checks` signature, return value, NEAR threshold (20%, ≤2 fails)
- `db.py` (lines 15-97, 100-135) — `_DDL` list, `init_db`, `upsert_alpha`, `upsert_checks`, `_ALPHA_COLS`; `runs` table schema
- `validate.py` (lines 23-94) — `validate` signature and logic
- `hunt.py` (lines 86-165, 195-310) — `_apply_additivity_gate` reference wiring; `grade.grade_many` call pattern; 401 pattern
- `delay0_candidates.py` (lines 48-89) — `_D0_CANDIDATES` structural model for `templates.py`
- `selfcorr.py` (lines 294-330) — `get_reference_pnl_paths`, `get_book_pnl_paths`
- `sync.py` (lines 77-142) — `sync_datafields` parameters; `datafields` table column mapping
- `probe_delay.py` (lines 1-80) — `probe_and_gate` signature; `DelayCoercedError`
- `.claude/commands/hunt.md` — command file structure to mirror for `bruteforce.md`
- `07-CONTEXT.md` — locked decisions D-01 through D-11
- `docs/plans/2026-06-11-additive-alpha-discovery-design.md` — design intent, candidate flow, Tool B definition

### Secondary (MEDIUM confidence)

- `.planning/REQUIREMENTS.md` — BF-01..BF-06, DLY-01/02, ADD-01..04 requirement text
- `.planning/ROADMAP.md` — Phase 7 success criteria (5 items)
- `.planning/STATE.md` — confirmed Phase 6 complete; no pending bugs blocking Phase 7

### Tertiary (LOW confidence)

- None — all findings sourced from live code.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all primitives read from live code with exact line citations
- Architecture: HIGH — pipeline structure follows live code exactly; no assumptions about BRAIN API beyond what grade.py already handles
- Pitfalls: HIGH — derived from actual code behavior (grade_many blocking, nested _grade_isolated, dedup behavior)
- Open questions: MEDIUM — Q1/Q2/Q3/Q4/Q5/Q6/Q7 all answered; remaining open questions are authoring decisions (template shapes), not unknowns

**Research date:** 2026-06-15
**Valid until:** 2026-07-15 (30 days; stable codebase; no external library churn)
