# Phase 6: Additivity Gate — Research

**Researched:** 2026-06-14
**Domain:** Local PnL correlation proxy + BRAIN /check confirmation gate
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Local proxy computes BOTH max-pairwise correlation (via `selfcorr.max_pearson`) AND correlation to the combined book PnL. Rank primarily by combined-book; expose max-pairwise to predict self_corr gate failures before spending `/check`.
- **D-02:** Proxy is primarily a ranker. Hard-drop only when local proxy corr is WELL ABOVE BRAIN's self_corr limit (limit + margin). BRAIN `/check` is the authoritative gate for survivors.
- **D-03:** "The book" = submitted/active competition alphas only (`status='ACTIVE'`). `get_reference_pnl_paths` selection must be explicit about this.
- **D-04:** Degraded/missing PnL → rank on what's available + warn (count skipped). Never hard-refuse. Fold in the `alphas.pnl_path`-null fix: clearing `pnl_cache/` alone doesn't force re-backfill because `pnl_path` is still set in the DB.
- **D-05:** Triage → confirm. Proxy reuses PnL sim already returned (free). BRAIN `/check` runs only on finalists. "No BRAIN call" in ADD-01 = no additional call beyond the sim that already happened.

### Claude's Discretion

- Combined-book aggregation method: sum of book daily returns vs equal-weight mean. Default: **summed daily returns** (simplest faithful form).
- Numeric pre-filter margin: a small fixed fraction of BRAIN's limit. Make it a named constant.

### Deferred Ideas (OUT OF SCOPE)

- CMD-01 — `/hunt --delay` selecting/ranking results through the gate (Phase 8)
- CMD-03 — `/iterate` decorrelate mode (Phase 9)
- Tool B (brute-force) integration (Phase 7)
- Bug #5 (grade.py second delay-blind dedup) — already fixed, not part of Phase 6
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ADD-01 | Estimate candidate's correlation to book from cheap local PnL proxy (no BRAIN call) | `_combined_book_corr()` using existing selfcorr helpers; `rank_by_proxy()` function |
| ADD-02 | Confirm finalist's additivity with BRAIN's real correlation check before submit-ready | `confirm_additive()` calling `trigger_correlation_check` + `poll_correlation`; reads limit from `is.checks` |
| ADD-03 | No alpha is submit-ready unless it passes the additivity gate (IS checks AND additivity) | Gate insertion point in `hunt.py` at `best_submittable` assignment (line 257/351) |
| ADD-04 | Gate is reusable as both float rank-score and bool filter | Single `AdditivityResult` dataclass carrying both; `rank_by_proxy()` returns list of scored candidates |
</phase_requirements>

---

## Summary

Phase 6 introduces `additivity.py`, a two-function module that prevents the 1Ygw09oz failure mode (alpha passes all IS checks but drops the team competition score by ~112 because it is correlated to the existing book). The module is pure composition over existing primitives: `rank_by_proxy()` calls `selfcorr.max_pearson` and a new `_combined_book_corr()` helper using `_date_overlap_returns` / `_pnls_to_daily_returns` / `_pearson`; `confirm_additive()` calls `grade.trigger_correlation_check` + `grade.poll_correlation` and reads BRAIN's limits from `is.checks` (no hardcode).

The BRAIN `/check` response shape is already fully implemented and tested in `grade.poll_correlation` (grade.py:526). The response is `{"is": {"checks": [...]}}` where each check dict has keys `name`, `result`, `value`, `limit`. SELF_CORRELATION and PROD_CORRELATION are filtered by name; the gate reads `c["limit"]` from the resolved response (same key the DB persists as `limit_val`). Nothing new to discover about the endpoint.

The reference set is `status='ACTIVE'` rows in `alpha_kb.db`. The DB currently has 16 ACTIVE alphas, all with `pnl_path` set in the DB to `pnl_cache/{id}.json`, but the `pnl_cache/` directory does not exist on disk. This is exactly the D-04 bug: `backfill_active_pnl` queries `WHERE pnl_path IS NULL` and skips those 16 rows because the DB says the path exists. The fix: check file existence and null `pnl_path` when the file is missing before running backfill, so the backfill query finds and re-fetches them.

**Primary recommendation:** Write `additivity.py` with `rank_by_proxy()` + `confirm_additive()` + a thin `AdditivityResult` dataclass; fix `backfill_active_pnl` to detect stale paths; insert the gate in `hunt.py` after `grade_many` results, before `_rank_best` promotes a candidate to `best_submittable`.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Local PnL proxy correlation | Application (Python) | — | Pure arithmetic over cached JSON files; no network call |
| Combined-book aggregation | Application (Python) | — | Sum of ACTIVE alpha daily returns; reuses selfcorr helpers |
| Pre-filter drop decision | Application (Python) | — | limit + margin compared locally; BRAIN never consulted at this stage |
| Authoritative correlation confirm | BRAIN API | Application (Python) | BRAIN `/check` is source of truth; app only polls and reads result |
| Submit-ready gate enforcement | hunt.py orchestrator | additivity.py | Hunt calls gate; gate does not call hunt |
| PnL cache backfill | selfcorr.backfill_active_pnl | BRAIN API | Sequential I/O before sim pool; 401 propagates |

---

## Standard Stack

This phase introduces no new external dependencies. All needed capabilities already exist in the project.

### Core Reused Primitives

| Module | Function | Line | Role in Phase 6 |
|--------|----------|------|-----------------|
| `selfcorr.py` | `max_pearson(candidate_path, reference_paths)` | 325 | Max-pairwise signal (D-01a); predicts BRAIN self_corr gate |
| `selfcorr.py` | `get_reference_pnl_paths(conn)` | 288 | Book reference set; D-03 requires restricting to `status='ACTIVE'` only |
| `selfcorr.py` | `get_selfcorr_limit(conn)` | 307 | Reads `SELF_CORRELATION` `limit_val` from checks table; basis for D-02 margin |
| `selfcorr.py` | `_date_overlap_returns(path_a, path_b)` | 124 | Date-aligned daily returns for two PnL paths |
| `selfcorr.py` | `_pnls_to_daily_returns(pnls)` | 70 | Cumulative PnL → daily returns; handles None/NaN forward-fill |
| `selfcorr.py` | `_pearson(x, y)` | 98 | Stdlib Pearson; returns 0.0 on < 2 points or zero-std |
| `selfcorr.py` | `load_returns(pnl_path)` | 268 | Load + filter to last 2 years; returns daily returns list |
| `selfcorr.py` | `backfill_active_pnl(client, conn, ...)` | 416 | Needs the D-04 stale-path fix |
| `grade.py` | `trigger_correlation_check(client, alpha_id)` | 512 | Kicks off BRAIN `/check` (GET, not POST — see finding below) |
| `grade.py` | `poll_correlation(client, alpha_id, timeout, interval)` | 526 | Polls until SELF_CORRELATION / PROD_CORRELATION leave PENDING |

### New Module

**`additivity.py`** — no external imports beyond stdlib; imports selfcorr and grade internally.

---

## Package Legitimacy Audit

No new packages are installed in this phase. All dependencies are stdlib (`math`, `json`, `pathlib`, `dataclasses`) or existing project modules. Section skipped per protocol.

---

## Architecture Patterns

### System Architecture Diagram

```
hunt() call
   │
   ├─ backfill_active_pnl()  ← D-04 fix: null stale pnl_path first
   │       └─ BRAIN GET /alphas/{id}/pnl  (only for truly missing files)
   │
   ├─ grade_many()  ← sims run here; each survivor has pnl_path after fetch_and_cache_pnl
   │       │
   │       └─ [for each IS-survivor] fetch_and_cache_pnl() → pnl_cache/{id}.json
   │
   ├─ additivity.rank_by_proxy(candidates, conn)   [NEW — zero BRAIN calls]
   │       ├─ get_reference_pnl_paths(conn, submitted_only=True)   ← D-03 change
   │       ├─ _combined_book_corr(candidate_path, ref_paths)       ← NEW helper
   │       │       ├─ load each ref_path → daily returns
   │       │       ├─ sum daily returns across refs (book daily return series)
   │       │       └─ _pearson(candidate_returns, book_returns)
   │       ├─ max_pearson(candidate_path, ref_paths)                ← existing
   │       └─ returns [AdditivityResult(...)] sorted by combined_corr asc
   │
   ├─ [D-02 soft pre-filter: drop if proxy_corr > limit + MARGIN]
   │
   ├─ additivity.confirm_additive(client, alpha_id, conn)   [NEW — ONE BRAIN call]
   │       ├─ trigger_correlation_check(client, alpha_id)
   │       ├─ poll_correlation(client, alpha_id)
   │       └─ reads c["result"] / c["limit"] from is.checks → bool + float
   │
   └─ _rank_best(confirmed_pass_ids, conn)  → best_submittable
```

### Recommended Project Structure

```
quant/
├── additivity.py          # NEW — rank_by_proxy(), confirm_additive(), AdditivityResult
├── selfcorr.py            # MODIFIED — get_reference_pnl_paths D-03 change
│                          #          — backfill_active_pnl D-04 stale-path fix
└── hunt.py                # MODIFIED — gate insertion before _rank_best
```

### Pattern 1: Combined-Book Correlation (D-01b)

The "combined book PnL" is the element-wise **sum** of each ACTIVE alpha's daily returns, aligned to the date overlap with the candidate. This is the correct additivity measure: the team score is driven by the aggregate book, not any individual alpha.

**Aggregation algorithm:**
1. For each reference path in the book, load daily returns with date labels.
2. Build a date → cumulative-returns map for each reference.
3. Find the intersection of all book dates with the candidate's dates.
4. On the overlap window, for each date: sum the daily return across all book alphas → scalar book_return[date].
5. Pearson correlate the candidate's daily returns against this book return series.

Key constraint: minimum overlap. The existing `_date_overlap_returns` enforces 60 trading days per pair. For the combined-book calculation, the minimum overlap should be the same 60 days, checked AFTER computing the book series (not before loading each reference). This means the book series is built from all references that have ANY data on overlap dates; references with no data on a given overlap date contribute 0 (or are simply absent from the sum).

**Simpler and correct** because `_pnls_to_daily_returns` forward-fills missing values — summing series across refs that already cover the same dates avoids per-pair min-overlap checks inside the aggregation.

### Pattern 2: AdditivityResult Dataclass (ADD-04)

```python
# Source: [ASSUMED — design recommendation, no existing prior art in codebase]
from dataclasses import dataclass
from typing import Optional

@dataclass
class AdditivityResult:
    alpha_id: str
    pnl_path: Optional[str]
    combined_corr: Optional[float]   # combined-book Pearson; primary rank key
    max_pairwise_corr: Optional[float]  # max-pairwise; predicts BRAIN self_corr gate
    proxy_drop: bool                 # True = hard-dropped by D-02 pre-filter
    skipped: bool                    # True = PnL missing; ranked last
    # confirm_additive fills these:
    brain_self_corr: Optional[float] = None
    brain_self_corr_result: Optional[str] = None  # PASS/FAIL/PENDING
    brain_self_corr_limit: Optional[float] = None  # read from is.checks, never hardcoded
    brain_prod_corr: Optional[float] = None
    brain_prod_corr_result: Optional[str] = None
    additive: Optional[bool] = None  # True = passed confirm_additive
```

The same object serves as both a float rank score (`combined_corr`) and a bool filter (`additive`, `proxy_drop`). No logic duplication.

### Pattern 3: rank_by_proxy() Signature

```python
def rank_by_proxy(
    candidates: list,   # list of dicts with keys: alpha_id, pnl_path
    conn: sqlite3.Connection,
    margin: float = PROXY_MARGIN,
) -> list[AdditivityResult]:
    """
    Zero BRAIN calls. Returns candidates sorted ascending by combined_corr
    (most additive first). Candidates with missing PnL are appended last.
    Candidates where combined_corr > limit + margin have proxy_drop=True.
    """
```

`PROXY_MARGIN` is a module-level named constant, not a magic number. Recommended starting value: `0.05` (5% above the BRAIN limit). This is Claude's discretion per D-05 in CONTEXT.md.

### Pattern 4: confirm_additive() Signature

```python
def confirm_additive(
    client,
    alpha_id: str,
    conn: sqlite3.Connection,
    timeout: int = 300,
    interval: int = 15,
) -> AdditivityResult:
    """
    ONE BRAIN call (GET /alphas/{id}/check). Reads limits from is.checks response
    (never hardcoded). Returns AdditivityResult with additive=True/False/None
    (None on timeout or missing SELF_CORRELATION in response).

    401 propagates immediately. TimeoutError converts to additive=None + warning.
    PROD_CORRELATION is optional — its absence is not an error.
    """
```

### Anti-Patterns to Avoid

- **Hardcoding 0.7:** BRAIN's self_corr limit is currently 0.7 in the DB, but `confirm_additive` MUST read `c["limit"]` from the live `/check` response, not from the DB. The DB `limit_val` is fine for the proxy pre-filter (it is already populated there), but the authoritative gate must use BRAIN's live response. [VERIFIED: grade.py:356 already does this correctly for `poll_correlation`.]
- **Calling trigger_correlation_check on every candidate:** Only finalists after the proxy pre-filter go through `/check`. Each check is a ~15–300 second polling round.
- **Summing returns without date alignment:** Each ACTIVE alpha's PnL covers different date ranges. Load each reference separately and sum only on the intersection with the candidate's date range.
- **Raising on missing book PnL:** If a book alpha's pnl_cache file is gone, skip it from the sum with a warning. The remaining book members are a valid (if incomplete) reference set. One missing file must not block the whole gate (D-04).

---

## Finding 1: BRAIN `/check` Response Shape

**Source:** `grade.py:526–585` (poll_correlation) and `grade.py:562–579` (response parsing). [VERIFIED: codebase]

The endpoint is `GET /alphas/{alpha_id}/check` (NOT POST). The async pattern:
1. First GET initiates computation → BRAIN may respond with `Retry-After` header.
2. Subsequent GETs: if `Retry-After > 0`, sleep and retry; when absent, the response is final.

**Response structure:**
```json
{
  "is": {
    "checks": [
      {"name": "SELF_CORRELATION",  "result": "PASS", "value": 0.346, "limit": 0.7},
      {"name": "PROD_CORRELATION",  "result": "PASS", "value": 0.23,  "limit": 0.7},
      {"name": "SHARPE",            "result": "PASS", "value": 1.62,  "limit": 1.25}
    ]
  }
}
```

**Key field names** (all verified in grade.py parsing code):
- `c["name"]` — string, e.g. `"SELF_CORRELATION"`, `"PROD_CORRELATION"`
- `c["result"]` — `"PASS"`, `"FAIL"`, or `"PENDING"` (PENDING while computing)
- `c["value"]` — float, the actual correlation value
- `c["limit"]` — float, BRAIN's live limit. **This is what `confirm_additive` must read.** Do NOT use the DB `limit_val` (which is stale after sync and populated by `db.upsert_checks` which maps `c.get("limit")` to `limit_val` column).

**DB mapping** (`db.upsert_checks`, db.py:112): `c.get("limit")` → `limit_val` column. So the DB field is `limit_val` but the BRAIN response field is `"limit"`.

**Existing usage** in grade.py:
```python
# grade.py:356–358
self_corr = corr_checks.get("SELF_CORRELATION", {}).get("value")
prod_corr  = corr_checks.get("PROD_CORRELATION", {}).get("value")

# grade.py:362
corr_failed = any(c.get("result") == "FAIL" for c in corr_checks.values())
```
`confirm_additive` follows the same pattern; additionally reads `c.get("limit")` for the live limit.

**PROD_CORRELATION note:** `poll_correlation` docstring (grade.py:540) explicitly notes "PROD_CORRELATION is commonly absent (requires a permission many accounts lack)". Current DB: only 2 resolved SELF_CORRELATION rows exist; no resolved PROD_CORRELATION rows. `confirm_additive` must treat missing PROD_CORRELATION as `None`, not failure.

---

## Finding 2: Combined-Book Correlation Implementation

**Source:** selfcorr.py:70–169 (helper functions). [VERIFIED: codebase]

### Building blocks already in selfcorr.py

`_date_overlap_returns(path_a, path_b)` (line 124) finds the date intersection between TWO PnL files. For the combined-book case we need to correlate the candidate against the SUM of N book series, so we cannot call this helper N times and average — we need a new `_combined_book_corr()` function.

**Correct algorithm for `_combined_book_corr(candidate_path, ref_paths)`:**

```python
# [ASSUMED — design; not yet in codebase]
def _combined_book_corr(candidate_path: str, ref_paths: list) -> Optional[float]:
    """Correlate candidate against summed book daily returns."""
    try:
        cand_data = json.loads(Path(candidate_path).read_text())
    except Exception:
        return None

    cand_map = dict(zip(cand_data.get("dates", []), cand_data.get("pnls", [])))
    if not cand_map:
        return None

    # Accumulate book returns per date across all references
    book_map: dict[str, float] = {}
    refs_used = 0
    for ref_path in ref_paths:
        try:
            ref_data = json.loads(Path(ref_path).read_text())
        except Exception:
            continue  # skip missing file; D-04: warn but don't block
        ref_dates = ref_data.get("dates", [])
        ref_pnls  = ref_data.get("pnls", [])
        if len(ref_dates) != len(ref_pnls) or not ref_dates:
            continue
        ref_map = dict(zip(ref_dates, ref_pnls))
        # Compute daily returns for this reference on dates in common with candidate
        overlap = sorted(set(ref_map) & set(cand_map))
        if len(overlap) < 2:
            continue
        ref_pnl_seq = [ref_map[d] for d in overlap]
        ref_daily   = _pnls_to_daily_returns(ref_pnl_seq)
        # Accumulate into book_map (daily returns, NOT cumulative)
        for date, ret in zip(overlap[1:], ref_daily):
            book_map[date] = book_map.get(date, 0.0) + ret
        refs_used += 1

    if refs_used == 0 or not book_map:
        return None

    # Align candidate returns to the same dates as the book series
    book_dates = sorted(book_map)
    cand_pnl_seq = [cand_map[d] for d in book_dates if d in cand_map]
    book_ret_seq = [book_map[d] for d in book_dates if d in cand_map]

    # Compute candidate daily returns on same dates
    # (we have cumulative pnl, need consecutive differences)
    # Simpler: reuse _date_overlap on candidate against a synthetic "book" path — but
    # since book_map is in memory, compute directly:
    overlap2 = [d for d in book_dates if d in cand_map]
    if len(overlap2) < 62:  # need 60+ daily returns → 62+ dates to get 61 returns
        return None

    cand_rets = _pnls_to_daily_returns([cand_map[d] for d in overlap2])
    book_rets = [book_map[d] for d in overlap2[1:]]  # skip first (no predecessor)

    n = min(len(cand_rets), len(book_rets))
    if n < 60:
        return None

    return _pearson(cand_rets[:n], book_rets[:n])
```

**Date alignment subtlety:** The candidate's cumulative PnL and the summed book daily returns must be on the same dates. The book daily returns for date D are `sum_k(pnl_k[D] - pnl_k[D-1])` across book alphas k. The candidate's daily return for date D is `cand_pnl[D] - cand_pnl[D-1]`. Both require the previous day's value, so the effective length after differencing is `|overlap| - 1`. The minimum check of 60 trading days is on the return series length, not the date-count.

**Refs_used warning:** If refs_used < total ACTIVE alphas, warn with count of skipped (D-04).

---

## Finding 3: Reference Set — D-03 Change to `get_reference_pnl_paths`

**Source:** selfcorr.py:288–304. [VERIFIED: codebase]

**Current query (line 301):**
```python
"SELECT pnl_path FROM alphas"
" WHERE pnl_path IS NOT NULL AND status IN ('pass', 'ACTIVE')"
```

This includes locally-passing `'pass'` alphas (our own simulation results). D-03 says the book = submitted/active competition alphas ONLY, not locally-passing candidates.

**D-03 change:** Remove `'pass'` from the IN clause. The new query:
```python
"SELECT pnl_path FROM alphas"
" WHERE pnl_path IS NOT NULL AND status = 'ACTIVE'"
```

**DB status values verified** (sqlite3 query against live `alpha_kb.db`):
- `'ACTIVE'` — synced from BRAIN via `sync.py`; these are the user's submitted/active competition alphas. Currently 16 rows, all with `pnl_path` set in DB. [VERIFIED: codebase + live DB]
- `'UNSUBMITTED'` — synced from BRAIN; not submitted to competition. Should NOT be in the book.
- `'pass'` — local simulation survivors; not submitted. Should NOT be in the book.
- `'fail'` — local simulation failures. Not in the book.

**Important:** The `status` field for BRAIN-synced alphas is written verbatim from `alpha.get("status", "")` in `sync.py:210`. BRAIN's status strings are UPPERCASE (`ACTIVE`, `UNSUBMITTED`). Locally-graded alphas use lowercase (`pass`, `fail`, `near`, `duplicate`, `timeout`, `error`, `queued`). The query `status = 'ACTIVE'` is case-sensitive in SQLite by default and correctly selects only BRAIN-synced submitted alphas.

**get_reference_pnl_paths impact:** The existing proxy_gate in `selfcorr.proxy_gate` calls `get_reference_pnl_paths`. After the D-03 change, proxy_gate will no longer include locally-passing candidates in the reference set for pre-sim filtering. This is intentional — the gate objective is book additivity, not avoiding duplicates of local-pass alphas. The D-04 exclusion of parent's own path (selfcorr.py:407) is still correct after this change.

**New function option:** Rather than changing the existing `get_reference_pnl_paths` (which is called by `proxy_gate` and the current behavior may be intentional for dedup), consider adding a new `get_book_pnl_paths(conn)` function that strictly returns `status='ACTIVE'` paths, and calling it from `additivity.py`. This avoids changing existing proxy_gate behavior.

---

## Finding 4: The pnl_path-null Refresh Bug (D-04 Fix)

**Source:** selfcorr.py:416–464 (`backfill_active_pnl`). [VERIFIED: codebase + live DB]

**The bug confirmed:** `backfill_active_pnl` at line 440 queries:
```python
"SELECT alpha_id FROM alphas WHERE status='ACTIVE' AND pnl_path IS NULL"
```

The live DB has 16 ACTIVE alphas; ALL 16 have `pnl_path` set (e.g. `pnl_cache/0mzapVMv.json`). However, the `pnl_cache/` directory does NOT exist on disk (confirmed by `find` on the filesystem). So `backfill_active_pnl` finds zero rows to re-fetch — the paths are stale (set, but the files are gone).

**Impact:** `get_reference_pnl_paths` returns 16 paths but every file read fails. `_date_overlap_returns` returns `([], [])` on `json.loads(Path(path).read_text())` exception (line 144). So the combined-book correlation and max-pairwise proxy always return 0.0 / None — the gate is silently a no-op.

**Correct fix:** Before running backfill, scan the DB for rows where `pnl_path IS NOT NULL` but the file does not exist, and null the `pnl_path` in those rows. The existing backfill query then finds them and re-fetches.

```python
# [ASSUMED — design recommendation]
def _null_stale_pnl_paths(conn: sqlite3.Connection) -> int:
    """Null pnl_path in DB where the cached file no longer exists.
    Returns count of rows nulled.
    Called by backfill_active_pnl before its SELECT query."""
    rows = conn.execute(
        "SELECT alpha_id, pnl_path FROM alphas WHERE pnl_path IS NOT NULL"
    ).fetchall()
    stale = [(alpha_id,) for alpha_id, pnl_path in rows
             if not Path(pnl_path).exists()]
    if stale:
        conn.executemany(
            "UPDATE alphas SET pnl_path=NULL WHERE alpha_id=?", stale
        )
        conn.commit()
    return len(stale)
```

This fix should live in `selfcorr.backfill_active_pnl`, called at the top before the existing query. Alternatively, `additivity.py` can call it before `rank_by_proxy` as a self-healing step. Placing it in `backfill_active_pnl` is cleaner because that is already the single call-site in `hunt.py`.

**Option B (lighter):** Change `get_reference_pnl_paths` to filter out non-existent paths:
```python
return [row[0] for row in rows if Path(row[0]).exists()]
```
This is safer at query time but does not fix the backfill skip — the ACTIVE alphas would still have stale `pnl_path` in the DB and backfill would not re-fetch them. Both fixes are needed: null stale paths (for backfill) AND existence check in `get_reference_pnl_paths` (defensive belt-and-suspenders).

---

## Finding 5: Reusable Score/Filter API (ADD-04)

The same gate object must serve as:
- **Float rank score:** `result.combined_corr` — lower = more additive. Sort ascending.
- **Bool filter:** `result.additive` (after confirm) or `not result.proxy_drop` (before confirm).

**Recommended pattern:** A single `AdditivityResult` dataclass (see Pattern 2 above) returned by both functions. `rank_by_proxy` returns a list of these sorted by `combined_corr` ascending. `confirm_additive` takes an `alpha_id` and returns one `AdditivityResult` with the BRAIN fields populated.

No logic duplication: `rank_by_proxy` computes proxy scores; `confirm_additive` calls the BRAIN check and fills `brain_*` fields on a fresh result. Neither calls the other.

**Usage as float:**
```python
ranked = additivity.rank_by_proxy(candidates, conn)
# ranked[0] is most additive; ranked[-1] is least
best = ranked[0]
score = best.combined_corr  # float in [-1, 1]; lower = more additive
```

**Usage as bool filter:**
```python
survivors = [r for r in ranked if not r.proxy_drop]
# Then for each finalist:
result = additivity.confirm_additive(client, alpha_id, conn)
if result.additive:
    submit_ready.append(alpha_id)
```

---

## Finding 6: Integration Point in hunt.py (ADD-03)

**Source:** hunt.py:46–391. [VERIFIED: codebase]

### Current submit-recommendation path

`best_submittable` is set in two places:
1. **Line 257** (inside the generation loop): `best_submittable = _rank_best(all_pass_ids, conn)`
2. **Line 351** (final pass after last generation): `best_submittable = _rank_best(all_pass_ids, conn)`

`_rank_best` (hunt.py:46–82) selects the alpha_id with highest Sharpe among PASS alphas. It has NO additivity awareness.

### Gate insertion design

The gate does not replace `_rank_best` — it filters which alpha_ids are eligible before `_rank_best` picks the best:

```python
# [ASSUMED — design recommendation]
# After all_pass_ids is accumulated:
# 1. Build candidate list for proxy ranking
pass_candidates = [
    {"alpha_id": aid, "pnl_path": conn.execute(
        "SELECT pnl_path FROM alphas WHERE alpha_id=?", (aid,)
    ).fetchone()[0]}
    for aid in all_pass_ids
]

# 2. Proxy rank + pre-filter
ranked = additivity.rank_by_proxy(pass_candidates, conn)
proxy_survivors = [r for r in ranked if not r.proxy_drop]

# 3. Confirm top-N finalists with BRAIN /check
confirmed = []
for r in proxy_survivors[:CONFIRM_LIMIT]:  # CONFIRM_LIMIT = named constant, e.g. 3
    result = additivity.confirm_additive(client, r.alpha_id, conn)
    if result.additive:
        confirmed.append(r.alpha_id)

# 4. best_submittable from confirmed-additive PASS alphas only
best_submittable = _rank_best(confirmed, conn)
```

**Where to insert:** Between the current `all_pass_ids.extend(pass_ids)` call and the `best_submittable = _rank_best(all_pass_ids, conn)` calls. Both occurrences need the gate (line 257 inside loop and line 351 final pass).

**Concurrency constraint:** `confirm_additive` calls `trigger_correlation_check` which makes a BRAIN GET request. This is NOT a simulation — it does not consume a sim slot. However it is a polling round (~15–300s per alpha). Run confirms sequentially (not in a thread pool). `≤3 concurrent sims` constraint from CLAUDE.md applies to `grade_many`, not to `/check` polling.

**401 propagation:** `trigger_correlation_check` calls `r.raise_for_status()` (grade.py:522). A 401 propagates up through `confirm_additive` → through the gate insertion block → to `hunt()` → to the CLI `except requests.exceptions.HTTPError` handler at line 447. This is already the correct pattern — never re-auth.

**Seam for Phase 7 and Phase 9:** The gate functions in `additivity.py` take `client`, `alpha_id`/`candidates`, `conn` — they are not coupled to `hunt.py`. Phase 7 (brute-force) and Phase 9 (`/iterate`) import `additivity` directly and call the same functions. No changes to `additivity.py` needed for those phases.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Date-aligned returns | Custom date math | `selfcorr._date_overlap_returns` | Already handles overlap, min-60-day guard, None/NaN |
| Pearson correlation | numpy or custom math | `selfcorr._pearson` | Stdlib-only; same implementation; already tested |
| BRAIN check polling | Custom retry loop | `grade.poll_correlation` | Already handles Retry-After, timeout, PROD_CORRELATION absence |
| Limit reading | Hardcode 0.7 | `selfcorr.get_selfcorr_limit(conn)` for proxy; `c["limit"]` from response for confirm | CLAUDE.md constraint; BRAIN is source of truth |
| Cumulative→daily conversion | Custom diff | `selfcorr._pnls_to_daily_returns` | Handles None/NaN forward-fill; already tested |

**Key insight:** This phase is pure composition. Every building block already exists and is tested. New code is the glue (`_combined_book_corr`, `rank_by_proxy`, `confirm_additive`) and the fix (`_null_stale_pnl_paths`).

---

## Common Pitfalls

### Pitfall 1: Empty Reference Set at Proxy Time

**What goes wrong:** `pnl_cache/` is missing (confirmed in this environment). `_combined_book_corr` reads zero files, returns `None` for every candidate. `rank_by_proxy` emits all results with `combined_corr=None`, `skipped=True` — the gate is a no-op.

**Why it happens:** `pnl_path` is set in the DB from a previous session, but the `pnl_cache/` directory was deleted or the system was run on a fresh checkout.

**How to avoid:** The D-04 fix (`_null_stale_pnl_paths` in `backfill_active_pnl`) corrects this automatically at hunt start. `rank_by_proxy` should log a WARNING when `refs_used == 0`.

**Warning signs:** All candidates have `skipped=True`; log line from `_combined_book_corr` showing `refs_used=0`.

### Pitfall 2: Stale limit in Pre-filter

**What goes wrong:** `get_selfcorr_limit(conn)` returns the DB value (currently 0.7) which may be stale if BRAIN changes its limit. The D-02 margin is applied to this value.

**Why it happens:** The DB limit is populated from `checks.limit_val`, set during grading. If no alphas have been graded recently, the limit may be stale.

**How to avoid:** This is acceptable for the proxy pre-filter (D-02 says it's a soft drop only when WELL ABOVE limit + margin). The authoritative gate (`confirm_additive`) reads the live limit from BRAIN's response. Document this clearly: proxy pre-filter uses DB limit; confirm uses live limit.

**Warning signs:** `get_selfcorr_limit` returns `None` (no graded alphas in DB yet). In this case `rank_by_proxy` should skip the pre-filter entirely and let all candidates through to `confirm_additive`.

### Pitfall 3: Correlating Against the Wrong Reference Set

**What goes wrong:** `get_reference_pnl_paths` includes locally-passing `'pass'` alphas. The book should be `ACTIVE` alphas only (D-03). A locally-passing alpha that was never submitted is not in the team competition score.

**How to avoid:** Use `get_book_pnl_paths(conn)` (new function in `selfcorr.py` querying `status='ACTIVE'` only) rather than `get_reference_pnl_paths`. Do not change `get_reference_pnl_paths` (it has a different purpose in `proxy_gate`: dedup against locally-passing alphas too).

**Warning signs:** Book reference set is much larger than 16 (the actual ACTIVE count). Correlation values are inflated.

### Pitfall 4: Consuming a /check Slot for Every Candidate

**What goes wrong:** `confirm_additive` is called inside `grade_many`'s concurrency pool, or called for all candidates rather than just finalists.

**Why it happens:** Misreading ADD-02 as "call `/check` after every IS survivor."

**How to avoid:** `confirm_additive` is called ONLY on finalists after `rank_by_proxy` and the proxy pre-filter. `grade_one` already calls `trigger_correlation_check` for IS survivors — those results are persisted to the DB. `confirm_additive` calls it AGAIN to get a fresh check, so it should only be called on the top-N candidates per run.

**Warning signs:** Multiple `/check` calls per alpha; timeout budget exceeded.

### Pitfall 5: Off-by-One in Combined-Book Return Series

**What goes wrong:** The book series has N dates; candidate has M dates. Overlap is K dates. `_pnls_to_daily_returns` returns K-1 values. Calling `_pearson` on series of length K (cumulative) vs K-1 (daily) produces a silently wrong correlation.

**How to avoid:** After computing `overlap2` dates, compute daily returns by differencing pnl values on `overlap2` (produces `len(overlap2) - 1` values). The book daily returns must also be built on the same `overlap2[1:]` dates (skipping the first date which has no predecessor). Verify `min(len(cand_rets), len(book_rets)) >= 60` before calling `_pearson`.

---

## Code Examples

### Check Response Parsing (confirm_additive)

```python
# Source: grade.py:562–579 [VERIFIED: codebase]
# poll_correlation returns a dict keyed by check name:
corr_checks = {
    c["name"]: c
    for c in checks
    if c["name"] in ("SELF_CORRELATION", "PROD_CORRELATION")
}
# Access:
sc = corr_checks.get("SELF_CORRELATION", {})
self_corr_value  = sc.get("value")    # float
self_corr_result = sc.get("result")   # "PASS" / "FAIL" / "PENDING"
self_corr_limit  = sc.get("limit")    # float — BRAIN's live limit; NEVER hardcode

pc = corr_checks.get("PROD_CORRELATION", {})
prod_corr_value  = pc.get("value")   # None if PROD not in response
```

### Existing max_pearson usage (max-pairwise signal)

```python
# Source: selfcorr.py:325 [VERIFIED: codebase]
max_corr = selfcorr.max_pearson(candidate_pnl_path, ref_paths)
# Returns 0.0 if no valid comparisons (graceful degrade D-13)
```

### Soft Pre-filter with Margin

```python
# Source: selfcorr.py:349–366 [VERIFIED: codebase — is_duplicate_by_pnl]
# The pattern for D-02:
PROXY_MARGIN = 0.05  # [ASSUMED: Claude's discretion from CONTEXT.md]
limit = selfcorr.get_selfcorr_limit(conn)
if limit is not None and combined_corr is not None:
    proxy_drop = combined_corr > (limit + PROXY_MARGIN)
else:
    proxy_drop = False  # cannot gate without limit; pass through
```

### backfill call in hunt.py (existing)

```python
# Source: hunt.py:172 [VERIFIED: codebase]
selfcorr.backfill_active_pnl(client, conn, db_path)
# D-04 fix: add _null_stale_pnl_paths(conn) call at top of backfill_active_pnl
```

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `PROXY_MARGIN = 0.05` (5% above BRAIN's limit) is a sensible starting value | Standard Stack / Pattern 3 | Pre-filter drops too many borderline candidates (too tight) or too few obvious failures (too loose). Named constant — easy to tune. |
| A2 | `CONFIRM_LIMIT = 3` (top-3 proxy survivors get BRAIN /check) is the right default | Finding 6: Integration | More candidates → more /check polling time. Fewer → risk of missing the best. Should be a named constant in hunt.py. |
| A3 | `_null_stale_pnl_paths` should live in `backfill_active_pnl` rather than `additivity.py` | Finding 4 | If placed in additivity.py, it could be called without the full backfill flow, leaving the DB inconsistent. |
| A4 | Combined-book uses SUM (not mean) of daily returns across book alphas | Finding 2 | Mean would reduce sensitivity to book size; sum is the natural "portfolio PnL" measure. CONTEXT.md Claude's Discretion endorses sum. |
| A5 | A separate `get_book_pnl_paths(conn)` function (status='ACTIVE' only) is better than modifying `get_reference_pnl_paths` | Finding 3 | Changing the existing function changes proxy_gate behavior. Separate function is safer. |

---

## Open Questions (RESOLVED)

1. **Should `confirm_additive` re-use an existing BRAIN check result from the DB?**
   - What we know: `grade.grade_one` already calls `trigger_correlation_check` + `poll_correlation` for every IS survivor and persists the result to `alphas.self_corr`. The result is in the DB.
   - What's unclear: Is the existing DB value fresh enough to use directly (avoiding a second `/check` call), or does it need a fresh check because the book has changed since grading?
   - Recommendation: For Phase 6, issue a fresh `/check` call in `confirm_additive` to get the current correlation against the live book. The existing `self_corr` in DB reflects the book state at grade time, which may have changed if new alphas were submitted. Document this clearly.

2. **What happens when `all_pass_ids` is empty at the end of hunt?**
   - What we know: `_rank_best` returns `None` for an empty list. The gate code must handle this.
   - Recommendation: If `all_pass_ids` is empty, skip the gate entirely and return `best_submittable=None` as before. Guard at top of gate insertion block.

3. **Should rank_by_proxy write scores back to the DB?**
   - What we know: No `additivity_score` column exists in `alphas`. Adding one would require a schema migration.
   - Recommendation: Phase 6 does NOT persist proxy scores to DB. The scores are ephemeral per-run rankings. If needed in future, a migration adds the column. Keep Phase 6 scope minimal.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| SQLite DB (`alpha_kb.db`) | Reference set, limit lookup | Yes | — | — |
| `pnl_cache/` directory | Book PnL files | NO (confirmed missing on disk) | — | D-04 fix re-fetches from BRAIN |
| BRAIN session (authenticated client) | `confirm_additive` | Yes (hunt.py pre-authenticates) | — | 401 surfaces cleanly |
| Python `dataclasses` (stdlib) | `AdditivityResult` | Yes (Python 3.7+) | — | — |

**Missing dependencies with fallback:**
- `pnl_cache/` directory: the D-04 fix (null stale paths + backfill re-fetch) handles this at runtime. The fix must run before any proxy correlation attempt.

---

## Security Domain

No new security surface introduced. Phase 6 makes no new network endpoints; it only calls `GET /alphas/{id}/check` (already used by grade.py). Auth constraints from CLAUDE.md (`never re-auth in-loop`, `401 propagates`) are inherited from `grade.trigger_correlation_check` / `grade.poll_correlation`. No user input is parsed; PnL files are JSON from BRAIN (same trust level as existing selfcorr.py reads).

---

## Sources

### Primary (HIGH confidence — verified by reading the actual codebase)
- `selfcorr.py:70–464` — all helper functions; their signatures, return types, and graceful degrade patterns
- `grade.py:512–585` — `trigger_correlation_check`, `poll_correlation`; BRAIN `/check` response shape
- `grade.py:354–379` — existing usage of `corr_checks.get("SELF_CORRELATION")` / `.get("value")` / `.get("result")`
- `hunt.py:46–391` — full `hunt()` function; `_rank_best`; `best_submittable` assignment points
- `db.py:14–55, 112–135` — schema (`alphas`, `checks` tables); `upsert_checks` field mapping (`c.get("limit")` → `limit_val`)
- `alpha_kb.db` (live query) — 16 ACTIVE alphas all with `pnl_path` set; `pnl_cache/` does not exist on disk; `SELF_CORRELATION` limit_val = 0.7 (two resolved rows)

### Secondary (MEDIUM confidence — inferred from code + DB state)
- `sync.py:210` — `status = alpha.get("status", "")` stores BRAIN's uppercase status strings verbatim; `ACTIVE` vs `pass` distinction

---

## Metadata

**Confidence breakdown:**
- BRAIN `/check` response shape: HIGH — verified line-by-line in grade.py
- Reference set / D-03 change: HIGH — verified in selfcorr.py + live DB query
- D-04 pnl_path bug: HIGH — confirmed by DB query (pnl_path set) + filesystem check (directory absent)
- Combined-book algorithm: MEDIUM — design is straightforward composition of verified helpers, but the exact implementation is new code
- Integration point in hunt.py: HIGH — two assignment sites clearly identified
- `PROXY_MARGIN`, `CONFIRM_LIMIT` values: LOW — Claude's discretion; named constants that can be tuned

**Research date:** 2026-06-14
**Valid until:** 2026-09-01 (stable codebase; BRAIN endpoint behavior is empirically confirmed)
