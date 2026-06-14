---
phase: 03-smart-iteration
reviewed: 2026-06-10T08:05:44Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - .claude/commands/hunt.md
  - .claude/commands/iterate.md
  - db.py
  - editor.py
  - find_alphas.py
  - fsa.py
  - grade.py
  - hunt.py
  - researcher.py
  - selfcorr.py
  - test_phase3.py
  - test_selfcorr.py
findings:
  critical: 6
  warning: 12
  info: 9
  total: 27
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-06-10T08:05:44Z
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Reviewed the Phase 3 "Smart Iteration" implementation: the `/hunt` orchestrator (`hunt.py`), hybrid editor (`editor.py`), local self-correlation pre-filter (`selfcorr.py`), FSA motif mining (`fsa.py`), grading integration (`grade.py`), supporting modules (`db.py`, `researcher.py`, `find_alphas.py`), command docs, and tests. Interfaces to adjacent modules were verified (`brain_client.BrainClient.get_pnl/simulate/get_alpha` exist; `ideator.queueable` contract matches; `validate.validate` signature matches).

The auth constraints are respected in structure (no `login()` call inside any loop body; 401s propagate from every BRAIN call path), the concurrency cap is enforced (`max_workers=min(n, 3)`), and the SDK `regular=` trap is avoided. However, **the core Phase 3 feature — the editor→grade mutation loop — is a no-op as written**: `editor.diagnose_and_mutate` pre-inserts every mutation into `alphas` as a `status='queued'` stub, and `grade.grade_one`'s Step 0 dedupe check (`db.expr_exists`) then rejects every one of those mutations as a "duplicate" before simulating. The loop burns one generation producing zero simulations and stops. Several secondary defects compound this (stubs classified as PASS, correlation results ignored when finalizing status, duplicates eligible for `best_submittable`, Gen 0 exempt from the sim budget).

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Editor-pre-inserted mutations are always skipped as duplicates — the editor→grade loop never simulates anything

**File:** `grade.py:113-116`, `editor.py:268-283`, `hunt.py:81-100,235-256`
**Issue:** `editor.diagnose_and_mutate` Step 5 pre-inserts every validated mutation into `alphas` as a `stub-<uuid8>` row with `status='queued'` (editor.py:274-283). `hunt._is_passable` was written specifically to let those queued stubs through to `grade_many` (hunt.py:81-100). But `grade_one` Step 0 runs its own dedupe first:

```python
existing_id = db.expr_exists(conn, expression)
if existing_id is not None:
    print(f"[grade] skip duplicate: {expression[:40]}")
    return {"expression": expression, "status": "duplicate", "alpha_id": existing_id}
```

The stub IS in the DB, so `expr_exists` returns `stub-...` and `grade_one` returns immediately — **no simulation ever runs for any editor mutation**. The comment in `iterate.md:82-84` ("`grade.grade_many` finds each expression via `db.expr_exists` and updates in place") and editor.py:271-272 ("grade_one will UPDATE the row with the real alpha_id") describe behavior that does not exist: `grade_one` never updates queued stubs; it bails out. Net effect: in `/hunt`, the mutation generation consumes zero sims, the duplicate results carry stub alpha_ids into the next classification pass (see CR-02), `near_ids` is empty, and the loop terminates "dry" after Gen 0. The entire D-16/D-17 iteration feature is dead. `/iterate` step 4 has the same failure.
**Fix:** In `grade_one`, treat `status='queued'` rows as gradable rather than duplicates, and update the stub row in place (preserving `parent_alpha_id`) instead of inserting a second row:

```python
existing_id = db.expr_exists(conn, expression)
if existing_id is not None:
    row = conn.execute("SELECT status, parent_alpha_id FROM alphas WHERE alpha_id=?",
                       (existing_id,)).fetchone()
    if row is None or row[0] != "queued":
        return {"expression": expression, "status": "duplicate", "alpha_id": existing_id}
    parent_alpha_id = parent_alpha_id or row[1]   # inherit lineage from stub
    stub_id_to_replace = existing_id              # delete/replace stub after sim
```

After simulation, `DELETE` the stub row (or `UPDATE` it to the real BRAIN alpha_id) so the expression does not exist twice in `alphas`.

### CR-02: `classify_from_checks` returns 'pass' for alphas with zero check rows — ungraded stubs and unknown alpha_ids are classified PASS

**File:** `editor.py:51-78`, `hunt.py:187-199,260-267`
**Issue:** When `checks` has no rows for an `alpha_id` (or only PENDING rows), `resolved`/`numeric_fails` are empty and the function returns `('pass', [])`. The docstring says "Only call for alphas that have completed Phase A IS checks", but `hunt()` calls it on **every** result's `alpha_id` — including `status='duplicate'` results whose `alpha_id` is an ungraded `stub-...` (via CR-01) and error results. Those stubs are appended to `pass_ids`/`all_pass_ids` and permanently pollute the PASS accumulator. An alpha that was never graded must never classify as PASS.
**Fix:** Return a distinct value for the empty case and have callers skip it:

```python
if not resolved:
    return "unknown", []   # no resolved checks — not gradable as pass
```

And in `hunt.py`, only classify results whose `status` is `pass`/`fail` (skip `duplicate`, `error`, `timeout`, `invalid`).

### CR-03: Phase B finalizes `status='pass'` unconditionally, ignoring SELF_CORRELATION / PROD_CORRELATION FAIL results

**File:** `grade.py:248-265`
**Issue:** After polling correlation checks:

```python
# Determine final status after correlation results
status_final = "pass"
```

`status_final` is hardcoded `"pass"` regardless of what `corr_checks` contain. An alpha whose `SELF_CORRELATION` resolves to `FAIL` (above BRAIN's limit — i.e., not submittable) is persisted with `alphas.status='pass'`. Everything keyed on `status='pass'` then mis-treats it: `fsa.mine_frequent_motifs` and `diversity_metric` count it as a passing alpha, `selfcorr.get_reference_pnl_paths` is fine, but most importantly the DB now records a non-submittable alpha as submittable. The comment claims a determination that is never made.
**Fix:**

```python
corr_failed = any(c.get("result") == "FAIL" for c in corr_checks.values())
status_final = "fail" if corr_failed else "pass"
```

(Read the result from BRAIN's checks — consistent with the CLAUDE.md "BRAIN is source of truth" rule.)

### CR-04: A known-duplicate (locally too-correlated) alpha can be crowned `best_submittable`

**File:** `hunt.py:187-199,258-267`, `grade.py:215-239`
**Issue:** When the local selfcorr filter fires, `grade_one` sets `alphas.status='duplicate'` and returns — but its Phase A checks (all PASS) were already persisted at grade.py:203, and `sharpe` is populated. `hunt` classifies by `classify_from_checks` only, which sees all-PASS checks and returns `'pass'`; the alpha enters `all_pass_ids`, and `_rank_best` (which never looks at `alphas.status`) can select it as `best_submittable`. The same applies to `status='timeout'` alphas whose correlation never resolved. The headline output of `/hunt` — "best new submittable alpha" — can be an alpha the system itself already determined is a non-submittable duplicate.
**Fix:** Filter on persisted status before ranking. Either skip non-`pass`-status results when building `pass_ids` in `hunt()` (`if r.get("status") != "pass": continue`), or make `_rank_best` exclude them:

```sql
SELECT sharpe FROM alphas WHERE alpha_id=? AND status='pass'
```

### CR-05: Gen 0 ignores the `max_sims` hard ceiling (D-17 violated)

**File:** `hunt.py:171-178`
**Issue:** The mutation generations trim their queue to the remaining budget (`[: max_sims - sims_used]`, hunt.py:242), but Gen 0 grades the entire ideator output unconditionally:

```python
queue = [c["expression"] for c in ideator.queueable(filtered)]
results = grade.grade_many(client, conn, queue, run_id, max_workers=3, db_path=db_path)
sims_used += len(queue)
```

If `generate_candidates` yields more queueable candidates than `max_sims` (e.g., 50 candidates with `max_sims=30`), hunt blows through the documented "hard simulation ceiling across all generations" on the very first batch. With ~2 min/sim this is a multi-hour overrun of the stated budget contract.
**Fix:** `queue = queue[:max_sims]` before calling `grade_many` (or `[: max_sims - sims_used]` for symmetry with the loop).

### CR-06: Hardcoded submittability thresholds (1.25 / 1.0 / 0.4) in `researcher.gather_insights` SQL

**File:** `researcher.py:128-149,176-182`
**Issue:** CLAUDE.md mandates that submittability thresholds "must be read from BRAIN's is.checks / DB at runtime — never hardcoded" and project context directs that violations are Critical. `gather_insights` hardcodes them in two query logic paths:

```sql
WHERE status='UNSUBMITTED' AND sharpe>=1.25 AND fitness>=1.0 AND turnover<=0.4
```

This is pre-existing code (the 1.25 literal was not added in this diff — the Phase 3 change added only `avoid_motifs` plumbing), and the blast radius is limited to insight text fed into LLM prompts rather than a pass/fail gate. It is flagged Critical per the project rule; if the team accepts the "informational-only" scope, downgrade with an explicit waiver.
**Fix:** Read limits from the `checks` table at runtime, falling back to skipping the insight when unavailable:

```python
sharpe_lim = conn.execute(
    "SELECT limit_val FROM checks WHERE name='LOW_SHARPE' AND limit_val IS NOT NULL LIMIT 1"
).fetchone()
```

and parameterize the query with the fetched values.

## Warnings

### WR-01: `grade_many` never passes `parent_alpha_id` — Hook A (proxy_gate) is unreachable and graded mutation rows lose lineage

**File:** `grade.py:290-338`, `hunt.py:252-255`
**Issue:** `grade_one` accepts `parent_alpha_id` and runs the pre-sim `proxy_gate` only when it is set, but `grade_many` has no parameter for it and always calls `grade_one(client, conn, expr, run_id)`. In the `/hunt` path the proxy gate (D-08a) therefore never executes. Worse, once CR-01 is fixed, `grade_one` would persist the graded alpha with `parent_alpha_id=None` (grade.py:176) while the stub row holding the real lineage sits orphaned at `status='queued'` — the same expression in `alphas` twice, with lineage on the wrong row.
**Fix:** When the dedupe lookup finds a queued stub (see CR-01 fix), inherit `parent_alpha_id` from the stub and replace the stub row. Optionally extend `grade_many` to accept `(expression, parent_alpha_id)` tuples.

### WR-02: `proxy_gate` compares the parent against a reference set that includes the parent itself

**File:** `selfcorr.py:324-358`, `selfcorr.py:243-259`
**Issue:** `get_reference_pnl_paths` returns paths for all `status IN ('pass','ACTIVE')` alphas. If the parent is a PASS alpha with cached PnL, its own `pnl_path` is in `reference_paths`; `_date_overlap_returns(parent_path, parent_path)` yields correlation 1.0, so `proxy_gate` returns True for **every** such parent — all of its mutations would be skipped pre-sim once WR-01 is fixed.
**Fix:** Exclude the parent's own path:

```python
reference_paths = [p for p in get_reference_pnl_paths(conn) if p != parent_pnl_path]
```

### WR-03: NEAR alphas from the final generation are dropped from `best_near`

**File:** `hunt.py:258-267`
**Issue:** The loop classifies `results` at the top of each iteration, then grades the next batch at the bottom. When the `for` loop exits by depth exhaustion, the last `grade_many` output is only re-scanned by the final pass — which collects `pass` alphas only. NEAR alphas discovered in the final generation never reach `best_near`, so `/hunt`'s documented handoff to `/iterate` ("best_near: feed to /iterate") silently loses the freshest candidates.
**Fix:** In the final pass, also collect `status == "near"` alpha_ids into `best_near` (with dedupe against the existing list).

### WR-04: `hunt()` never writes a `runs` row — archetype rotation is frozen across hunt runs

**File:** `hunt.py:142,161`, `researcher.py:204-227`
**Issue:** `select_archetype` cycles archetypes by `SELECT count(*) FROM runs`. `find_alphas()` writes a runs row per invocation, but `hunt()` generates a `run_id` and never inserts into `runs`. Consecutive `/hunt` runs therefore see the same run count and research the **same archetype every time**, directly undermining the diversity objective (criterion 4), and run metadata (thesis, iterations, num_pass) is lost for hunt runs.
**Fix:** Insert a runs row at the start of `hunt()` (mirroring `find_alphas.write_runs_row`), and update `num_pass`/`iterations` before returning.

### WR-05: `status='near'` is never persisted — `/iterate`'s `status IN ('near','fail')` query can never match 'near'

**File:** `.claude/commands/iterate.md:20-29,103-110`, `grade.py:169`, `hunt.py:187-199`
**Issue:** The only statuses ever written to `alphas.status` are `pass`, `fail`, `duplicate`, `timeout`, and `queued`. NEAR is computed in memory by `classify_from_checks` and never written back. The `/iterate` command's query `WHERE status IN ('near', 'fail')` will return NEAR alphas only because they happen to be stored as `'fail'` — the displayed status column is wrong, and the doc's NEAR-vs-FAIL prioritization table cannot be driven from the DB.
**Fix:** Either persist the classification (`UPDATE alphas SET status='near'` after `classify_from_checks` in hunt's loop) or change `iterate.md` to reclassify each `'fail'` row via `editor.classify_from_checks` before display.

### WR-06: Sequential `grade_many` path lacks per-candidate failure isolation

**File:** `grade.py:310-314`
**Issue:** The concurrent path wraps `grade_one` in try/except so one candidate's failure can't kill the batch (grade.py:325-332), but the sequential path (`max_workers <= 1`) has no such isolation — a single `RuntimeError` from `_simulate_to_alpha` aborts all remaining expressions. Inconsistent with the stated intent of commit 551c8f4 ("isolate per-candidate failures in grade_many").
**Fix:** Apply the same try/except (401 re-raised, other exceptions → `{"status": "error"}`) around the sequential `grade_one` call.

### WR-07: `fsa.extract_abstract_subtrees` does not recurse into BinOp/UnaryOp/keyword nodes — motifs in compound expressions are invisible

**File:** `fsa.py:72-81`
**Issue:** `_visit` only descends through `ast.Call.args`. A top-level arithmetic combination — `rank(close) - rank(open)` — is a `BinOp`, so `_visit(tree.body)` matches nothing and the expression contributes **zero** motifs; nested calls inside BinOp args (`rank(ts_mean(close,5) - ts_mean(open,5))` → inner `ts_mean` calls) are likewise never extracted. Both the mining side (motif frequencies undercounted) and the hard filter side (`filter_candidates` cannot drop a banned motif hidden inside arithmetic) are weakened — candidates can trivially bypass FSA by wrapping a banned motif in `... * 1` style arithmetic.
**Fix:** Recurse through all child nodes:

```python
def _visit(node):
    if isinstance(node, ast.Call):
        fname = node.func.id if isinstance(node.func, ast.Name) else '?'
        shapes.append(f"{fname}({','.join(_arg_type(a) for a in node.args)})")
    for child in ast.iter_child_nodes(node):
        _visit(child)
```

### WR-08: `_call_llm_editor` fabricates a BRAIN-style 401 from Claude CLI stderr — misleading abort with re-auth guidance

**File:** `editor.py:166-175`
**Issue:** When the `claude` subprocess fails with "401"/"Unauthorized"/"not authenticated" in stderr (a Claude CLI auth problem, unrelated to BRAIN), the code constructs a synthetic `requests.HTTPError(status_code=401)`. That propagates through `diagnose_and_mutate` → `hunt()` → the CLI handler, which prints "AUTH EXPIRED — Re-run hunt.py to re-authenticate" and exits. The user is told to redo BRAIN biometric auth for a Claude CLI problem — repeated re-runs risk exactly the 429 BIOMETRICS_THROTTLED lockout the constraint exists to prevent, and the substring match (`"401" in stderr`) can false-positive on any stderr containing "401".
**Fix:** Raise a distinct exception type (e.g., `class EditorAuthError(RuntimeError)`) for Claude CLI auth failures so the orchestrator can stop with an accurate message ("Claude CLI not authenticated — run `claude login`") instead of conflating it with BRAIN session expiry.

### WR-09: `sims_used` counts non-simulated results — budget and reporting are inaccurate

**File:** `hunt.py:178,256`
**Issue:** `sims_used += len(queue)` charges the budget for every queued expression, including those that returned `duplicate` (dedupe/proxy-gate skip, no API call), `invalid`, and `error` before any simulation ran. Combined with CR-01 (where 100% of a mutation batch returns `duplicate`), `sims_used` can report a full generation of sims that never happened, prematurely triggering the budget stop condition.
**Fix:** Count from results: `sims_used += sum(1 for r in results if r.get("status") not in ("duplicate", "invalid", "error"))`.

### WR-10: Empty/missing `is.checks` yields `is_survivor=True` and `status='pass'` with NULL metrics

**File:** `grade.py:144-169`
**Issue:** If BRAIN returns an alpha dict without an `is` block (or with an empty `checks` array — e.g., a partially-finished sim slipping past the SDK's wait()), `checks_raw=[]` makes `all(...)` vacuously True, so the alpha is persisted as `status='pass'` with NULL sharpe/fitness, and Phase B is triggered on it. A no-data alpha must not be recorded as passing.
**Fix:** Guard explicitly: `is_survivor = bool(checks_raw) and all(...)`; if `checks_raw` is empty, set `status='error'` (or `'unknown'`) and skip Phase B.

### WR-11: `poll_correlation` crashes on non-numeric Retry-After header

**File:** `grade.py:399`
**Issue:** `float(r.headers.get("Retry-After", 0))` raises `ValueError` if BRAIN (or an intermediary proxy) sends an HTTP-date format Retry-After (valid per RFC 7231) or any non-numeric value. In the sequential path this kills the whole batch (per WR-06); in the concurrent path the candidate is marked `error` after a possibly-successful sim, wasting the sim slot's result.
**Fix:**

```python
try:
    retry_after = float(r.headers.get("Retry-After", 0))
except (TypeError, ValueError):
    retry_after = float(interval)
```

### WR-12: `test_phase3.py` copies the live `alpha_kb.db` into test fixtures — non-hermetic, state-dependent tests

**File:** `test_phase3.py:31-40`
**Issue:** `_make_test_db` copies the production `alpha_kb.db` (384+ live rows) when present. Test outcomes then depend on live DB contents: `diagnose_and_mutate` in `test_criterion_1_near_classification` runs `db.expr_exists` and validation against live catalog/alpha data; future live rows whose check names or expressions collide with fixtures could flip assertions. The same suite passes on a fresh DB and may fail (or pass for the wrong reason) on a grown live DB — a flaky-test pattern affecting reliability.
**Fix:** Always start from a fresh `db.init_db` file and insert only the fixture rows each test needs (the FSA test already does `DELETE FROM alphas` for exactly this reason — apply that discipline suite-wide by not copying the live DB at all).

## Info

### IN-01: Deprecated `datetime.utcnow()` usage

**File:** `db.py:100`, `grade.py:172,246,269`
**Issue:** `datetime.utcnow()` is deprecated (Python 3.12+; this venv is 3.14) and produces naive timestamps, while `editor.py`/`hunt.py`/`find_alphas.py` use timezone-aware `datetime.now(timezone.utc)` — mixed timestamp formats in the same tables.
**Fix:** Standardize on `datetime.now(timezone.utc).isoformat()`.

### IN-02: Loose 401 detection at the hunt CLI

**File:** `hunt.py:341-343`
**Issue:** `"401" in str(e)` can false-positive on any error string containing "401" (URLs, ids). Defense-in-depth, but imprecise.
**Fix:** Rely solely on `e.response.status_code == 401`.

### IN-03: Dead non-401 HTTPError branch in `backfill_active_pnl`

**File:** `selfcorr.py:396-399`
**Issue:** `fetch_and_cache_pnl` already swallows all non-401 HTTPErrors (returns None), so the `except HTTPError` non-401 branch in the caller is unreachable dead code.
**Fix:** Remove the branch or note that only 401 can propagate.

### IN-04: Each alpha is classified twice per generation in hunt

**File:** `hunt.py:191,222`
**Issue:** `classify_from_checks` runs once when building `near_ids`/`pass_ids` and again when collecting mutations — redundant DB round-trips and a risk of divergence if classification ever becomes non-idempotent.
**Fix:** Classify once per result into a dict and reuse.

### IN-05: `runs.notes` stores an absolute path; docstring promises a relative path

**File:** `find_alphas.py:334-343,426`
**Issue:** `note_path = str(THESES_DIR / note_filename)` is absolute (THESES_DIR derives from `Path(__file__).parent`), but `write_runs_row`'s contract says "relative path to the emitted thesis note". Breaks portability of the DB across machines/checkouts.
**Fix:** Store `os.path.relpath(note_path, _HERE)` or document the absolute-path behavior.

### IN-06: `max_pearson` ignores negative correlations

**File:** `selfcorr.py:293-301`
**Issue:** `if corr > max_corr` with `max_corr=0.0` discards strong negative correlations. If BRAIN's self-correlation check considers |corr| (an inverted clone of an existing alpha), the local pre-filter under-detects.
**Fix:** Confirm BRAIN semantics; if absolute, use `corr = abs(_pearson(...))`.

### IN-07: Leading None values forward-fill to 0.0, creating a spurious first return

**File:** `selfcorr.py:85-95`
**Issue:** `last_valid = 0.0` means a PnL series starting with Nones fills them as 0.0; the first real value then produces one artificially large daily return, slightly distorting Pearson.
**Fix:** Skip leading Nones (back-fill with the first valid value) before differencing.

### IN-08: `get_selfcorr_limit` selects an arbitrary row

**File:** `selfcorr.py:273-277`
**Issue:** `LIMIT 1` without `ORDER BY` returns an unspecified row; if BRAIN ever changes the SELF_CORRELATION limit, a stale value may be used.
**Fix:** `ORDER BY checked_at DESC LIMIT 1`.

### IN-09: Migration swallows all `sqlite3.OperationalError`s, not just duplicate-column

**File:** `db.py:74-78`
**Issue:** The idempotent `ALTER TABLE` catch ignores any OperationalError (locked DB, disk I/O, malformed schema), potentially hiding a failed migration as success.
**Fix:** Re-raise unless `"duplicate column name" in str(e)`.

---

_Reviewed: 2026-06-10T08:05:44Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
