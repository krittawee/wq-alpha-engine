---
phase: 03-smart-iteration
fixed_at: 2026-06-10T08:25:00Z
review_path: .planning/phases/03-smart-iteration/03-REVIEW.md
iteration: 1
findings_in_scope: 18
fixed: 18
skipped: 0
status: all_fixed
---

# Phase 3: Code Review Fix Report

**Fixed at:** 2026-06-10T08:25:00Z
**Source review:** `.planning/phases/03-smart-iteration/03-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 18 (6 Critical + 12 Warning)
- Fixed: 18
- Skipped: 0

## Fixed Issues

### CR-01: Editor-pre-inserted mutations are always skipped as duplicates

**Files modified:** `grade.py`
**Commit:** 48671a4
**Applied fix:** `grade_one` Step 0 now checks `status` of the existing row. If `status='queued'`, inherits `parent_alpha_id` from the stub, records `stub_id_to_replace`, and continues to simulate. After `db.upsert_alpha` inserts the real graded row, the stub is `DELETE`d so the expression exists only once in `alphas`.

---

### CR-02: `classify_from_checks` returns 'pass' for alphas with zero check rows

**Files modified:** `editor.py`, `hunt.py`
**Commit:** 48671a4
**Applied fix:** `classify_from_checks` now returns `("unknown", [])` when `rows` (the raw DB result) is empty (alpha was never graded — e.g. a queued stub). The all-PENDING case (Phase B in flight) correctly continues to return `("pass", [])` per D-05 Pitfall 2. In `hunt.py`, both the classification loop and the mutation-collection loop now skip results whose `status` is not `"pass"` or `"fail"` before calling `classify_from_checks`.

---

### CR-03: Phase B finalizes `status='pass'` unconditionally

**Files modified:** `grade.py`
**Commit:** 48671a4
**Applied fix:** Replaced `status_final = "pass"` with:
```python
corr_failed = any(c.get("result") == "FAIL" for c in corr_checks.values())
status_final = "fail" if corr_failed else "pass"
```
BRAIN is now the source of truth for correlation-pass/fail determination.

---

### CR-04: A locally-duplicate alpha can be crowned `best_submittable`

**Files modified:** `hunt.py`
**Commit:** 261e833
**Applied fix:** `_rank_best` now queries `WHERE alpha_id=? AND status='pass'` — alphas with `status='duplicate'`, `'timeout'`, `'near'`, etc. are excluded from best-of ranking even if they have sharpe populated from Phase A.

---

### CR-05: Gen 0 ignores the `max_sims` hard ceiling

**Files modified:** `hunt.py`
**Commit:** 261e833
**Applied fix:** Added `queue = queue[:max_sims - sims_used]` after building the Gen 0 queue from `ideator.queueable(filtered)`, symmetric with the mutation-generation trim.

---

### CR-06: Hardcoded submittability thresholds (1.25 / 1.0 / 0.4) in `researcher.gather_insights`

**Files modified:** `researcher.py`
**Commit:** e3988dc
**Applied fix:** `gather_insights` now reads `LOW_SHARPE`, `LOW_FITNESS`, and `HIGH_TURNOVER` `limit_val` from the `checks` table at runtime (`ORDER BY checked_at DESC LIMIT 1`), falling back to `1.25` / `1.0` / `0.4` only when no rows exist. The clean-pool SQL query is parameterized with the fetched values.

---

### WR-01: `grade_many` never passes `parent_alpha_id`

**Files modified:** `grade.py`, `hunt.py`
**Commit:** 261e833
**Applied fix:** `grade_many` now accepts a `parent_map: Optional[dict]` kwarg (and also normalizes `list[tuple[str, str|None]]` input). `hunt()` builds a `parent_map` dict while iterating mutations and passes it to the `grade_many` mutation call. CR-01 in `grade_one` also inherits lineage from the queued stub when `parent_alpha_id` is None.

---

### WR-02: `proxy_gate` compares parent against reference set that includes itself

**Files modified:** `selfcorr.py`
**Commit:** 7df4d03
**Applied fix:** After fetching `reference_paths`, the parent's own path is excluded: `reference_paths = [p for p in reference_paths if p != parent_pnl_path]`. If no references remain after exclusion, returns `False` (allow sim to proceed).

---

### WR-03: NEAR alphas from the final generation are dropped from `best_near`

**Files modified:** `hunt.py`
**Commit:** 261e833
**Applied fix:** The final-pass reclassification loop (after the `for gen` loop exits) now also collects `status == "near"` alpha_ids into `best_near` (deduped against the existing list).

---

### WR-04: `hunt()` never writes a `runs` row

**Files modified:** `hunt.py`
**Commit:** 261e833
**Applied fix:** At the start of `hunt()`, inserts a row into `runs` with `run_id`, empty `thesis` placeholder, `started_at`, `iterations=0`, `num_pass=0`. After thesis is built, updates the thesis field. Before building the result dict, updates `num_pass=len(all_pass_ids)` and `iterations=generations_count`.

---

### WR-05: `status='near'` is never persisted to DB

**Files modified:** `hunt.py`
**Commit:** 261e833
**Applied fix:** When `classify_from_checks` returns `'near'` in both the main generation loop and the final-pass loop, `conn.execute("UPDATE alphas SET status='near' WHERE alpha_id=?", ...)` is called immediately. `conn.commit()` is called after the inner loop in both cases.

---

### WR-06: Sequential `grade_many` path lacks per-candidate failure isolation

**Files modified:** `grade.py`
**Commit:** 7df4d03
**Applied fix:** The sequential path now wraps each `grade_one` call in a try/except block matching the concurrent path: 401 `HTTPError` re-raised; any other exception produces `{"status": "error", "expression": expr, "error": str(e)}`.

---

### WR-07: `fsa.extract_abstract_subtrees` does not recurse into BinOp/UnaryOp nodes

**Files modified:** `fsa.py`
**Commit:** 7df4d03
**Applied fix:** `_visit` now uses `ast.iter_child_nodes(node)` for recursion instead of explicitly iterating `node.args`. This surfaces motifs inside `BinOp`, `UnaryOp`, keyword nodes, and any other compound AST structure.

---

### WR-08: `_call_llm_editor` fabricates a BRAIN-style 401

**Files modified:** `editor.py`, `hunt.py`
**Commit:** 48671a4 (editor.py), 261e833 (hunt.py)
**Applied fix:** Defined `class EditorAuthError(RuntimeError)` in `editor.py`. `_call_llm_editor` raises `EditorAuthError` (with accurate message) instead of constructing a synthetic `requests.HTTPError`. `diagnose_and_mutate` re-raises `EditorAuthError` immediately. The hunt CLI catches `editor.EditorAuthError` separately and prints "run 'claude login'" guidance instead of BRAIN re-auth advice.

---

### WR-09: `sims_used` counts non-simulated results

**Files modified:** `hunt.py`
**Commit:** 261e833
**Applied fix:** Both `sims_used +=` sites (Gen 0 and mutation generation) now use `sum(1 for r in results if r.get("status") not in ("duplicate", "invalid", "error"))` instead of `len(queue)`.

---

### WR-10: Empty/missing `is.checks` yields `is_survivor=True` and `status='pass'`

**Files modified:** `grade.py`
**Commit:** 48671a4
**Applied fix:** After `db.upsert_alpha` and the stub deletion, an explicit guard `if not checks_raw:` marks the alpha as `status='error'` and returns immediately, skipping Phase B. A no-data alpha is never recorded as passing.

---

### WR-11: `poll_correlation` crashes on non-numeric Retry-After header

**Files modified:** `grade.py`
**Commit:** 48671a4
**Applied fix:** Wrapped `float(r.headers.get("Retry-After", 0))` in `try/except (TypeError, ValueError)`, falling back to `float(interval)` on parse failure.

---

### WR-12: `test_phase3.py` copies the live `alpha_kb.db` into test fixtures

**Files modified:** `test_phase3.py`
**Commit:** d2ec34d
**Applied fix:** `_make_test_db` now always returns a fresh path inside `tmpdir` and lets `db.init_db` create it from scratch. The `shutil.copy` call and the `if os.path.exists(live_db)` branch are removed entirely. The `shutil` import is also removed.

---

## Skipped Issues

None — all in-scope findings were fixed.

---

_Fixed: 2026-06-10T08:25:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
