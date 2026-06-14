---
phase: 03-smart-iteration
verified: 2026-06-10T09:15:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run hunt.py end-to-end against a live BRAIN session with max_depth=1 max_sims=5"
    expected: "Gen 0 produces candidates; at least one NEAR/FAIL alpha triggers diagnose_and_mutate; Gen 1 simulates the mutations (not skipped as duplicates); sims_used increments beyond Gen 0 count; best_submittable or best_near is populated"
    why_human: "The CR-01 fix (grade_one treats queued stubs as gradable) is only exercisable with a live BRAIN session. The mutation loop being 'not dead' can only be confirmed when simulate() actually runs on a stub-originated expression."
  - test: "Run hunt.py with a PASS alpha in the DB whose parent is also PASS and has pnl_cache/ data"
    expected: "proxy_gate does not block all mutations of that parent (self-exclusion fix WR-02 prevents 1.0 self-correlation from gating every mutation)"
    why_human: "proxy_gate's self-exclusion logic requires real pnl_cache files and a real BRAIN client to exercise the comparison path. No mock test covers the actual file comparison path."
  - test: "Inspect diversity_before vs diversity_after in a real hunt run output"
    expected: "top_motif_share drops or stabilises after FSA filtering; not the same as before"
    why_human: "diversity_metric output depends on accumulated PASS alphas from live runs. Cannot verify the before/after spread is meaningful without real grading results."
---

# Phase 3: Smart Iteration Verification Report

**Phase Goal:** Smart Iteration — autonomous loop (editor classify/mutate + selfcorr pre-filter + FSA diversity) that turns NEAR alphas into PASS alphas without human intervention.
**Verified:** 2026-06-10T09:15:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | `editor.classify_from_checks` returns PASS/NEAR/FAIL with diagnosis; `diagnose_and_mutate` proposes targeted mutations stored with `parent_alpha_id` lineage and `status='queued'` | VERIFIED | `editor.py` implements both functions; `classify_from_checks` uses HARD_FAIL_CHECKS frozenset, EPSILON, PENDING filter, NEAR D-05..D-07 algorithm; `diagnose_and_mutate` pre-inserts stubs with `parent_alpha_id=alpha_id` and `status='queued'` before returning; `UPDATE alphas SET diagnosis=?` persists diagnosis to source alpha |
| 2 | Graded mutations have `parent_alpha_id` set; editor stubs (`status='queued'`) are replaced (not duplicated) when graded; `grade_one` treats queued stubs as gradable | VERIFIED | `grade.py:113-127` detects queued stubs via `SELECT status, parent_alpha_id`, inherits lineage, records `stub_id_to_replace`; `grade.py:217-219` DELETEs the stub after inserting the real graded row; `hunt.py:84-103` `_is_passable()` guard passes queued stubs through to `grade_many` |
| 3 | `selfcorr.proxy_gate` blocks pre-sim; `selfcorr.is_duplicate_by_pnl` dedupes post-IS; correlation limit read from DB at runtime (not hardcoded) | VERIFIED | `grade.py:139-142` Hook A calls `selfcorr.proxy_gate` before simulate when `parent_alpha_id` is set; `grade.py:250-268` Hook B calls `fetch_and_cache_pnl` + `is_duplicate_by_pnl` after IS survivor check before `trigger_correlation_check`; `selfcorr.get_selfcorr_limit` reads `limit_val FROM checks WHERE name='SELF_CORRELATION'` — no literal 0.7 anywhere in implementation code |
| 4 | `fsa.mine_frequent_motifs` with cold-start guard; `fsa.filter_candidates` applied in find_alphas; `diversity_metric` available | VERIFIED | `fsa.py` implements all three functions; cold-start guard returns `[]` when `len(pass_exprs) < DEFAULT_MIN_SAMPLES (5)`; `find_alphas.py:397-414` calls `mine_frequent_motifs` then `filter_candidates`; `hunt.py:168,336` snapshots `diversity_before/after` via `fsa.diversity_metric` |

**Score:** 4/4 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `editor.py` | Hybrid Editor — classify + mutate | VERIFIED | 320 lines; `classify_from_checks`, `diagnose_and_mutate`, `HARD_FAIL_CHECKS`, `EPSILON`, `EditorAuthError` all present |
| `selfcorr.py` | PnL fetch/cache + Pearson pre-filter | VERIFIED | 420 lines; all 8 public functions present; `proxy_gate` self-exclusion (WR-02) wired |
| `fsa.py` | AST subtree mining + filter + diversity | VERIFIED | 210 lines; `extract_abstract_subtrees` (BinOp recursion WR-07), `mine_frequent_motifs`, `filter_candidates`, `diversity_metric` all present |
| `grade.py` | Extended grader + selfcorr hooks | VERIFIED | Hook A (`proxy_gate`) at line 139; Hook B (`fetch_and_cache_pnl` + `is_duplicate_by_pnl`) at lines 250-268; queued stub handling (CR-01) at lines 113-127 + 217-219; Phase B `status_final` from `corr_checks` (CR-03) at lines 279-280 |
| `hunt.py` | Bounded loop + diversity snapshots | VERIFIED | `max_depth`/`max_sims`/dry-stop; `_is_passable` guard; `parent_map` passed to `grade_many`; diversity before/after; `sims_used` counts only non-skipped results (WR-09) |
| `find_alphas.py` | FSA avoid_motifs integrated | VERIFIED | `mine_frequent_motifs` at line 397; `filter_candidates` at line 410; `avoid_motifs` passed to `researcher.build_thesis` at line 401 |
| `db.py` | `diagnosis TEXT` column in schema | VERIFIED | `diagnosis TEXT` in `_DDL` CREATE TABLE; `"diagnosis"` in `_ALPHA_COLS`; idempotent `ALTER TABLE` in `init_db()` |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `editor.classify_from_checks` | `checks` table | `SELECT ... WHERE result != 'PENDING'` | VERIFIED | `grade.py:61-67` filters PENDING rows |
| `editor.diagnose_and_mutate` | `validate.validate + db.expr_exists` | mutation gate | VERIFIED | `editor.py:268-273` gates each proposed expression |
| `editor.diagnose_and_mutate` | `alphas.diagnosis` | `UPDATE alphas SET diagnosis=?` | VERIFIED | `editor.py:309` parameterized UPDATE |
| `editor.diagnose_and_mutate` pre-insert | `alphas.parent_alpha_id` | `db.upsert_alpha` with `status='queued'` | VERIFIED | `editor.py:294-304` |
| `grade_one` | `selfcorr.proxy_gate` | before `_simulate_to_alpha` when `parent_alpha_id` known | VERIFIED | `grade.py:139-142` |
| `grade_one` | `selfcorr.is_duplicate_by_pnl` | after `is_survivor`, before `trigger_correlation_check` | VERIFIED | `grade.py:250-268` |
| `find_alphas.find_alphas` | `fsa.mine_frequent_motifs` | called before `generate_candidates` | VERIFIED | `find_alphas.py:397` |
| `hunt` | `grade_many` with `parent_map` | mutations tracked with parent lineage | VERIFIED | `hunt.py:302-306` passes `parent_map` |
| `grade_one` queued stub | `DELETE FROM alphas` after real row insert | stub replaced not duplicated | VERIFIED | `grade.py:217-219` |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `editor.classify_from_checks` | `rows` from checks table | `SELECT ... FROM checks WHERE alpha_id=?` | Yes — parameterized DB read | FLOWING |
| `selfcorr.get_selfcorr_limit` | `limit_val` | `SELECT limit_val FROM checks WHERE name='SELF_CORRELATION'` | Yes — runtime DB read, no hardcode | FLOWING |
| `fsa.mine_frequent_motifs` | `pass_exprs` | `SELECT expression FROM alphas WHERE status='pass'` | Yes — live DB query | FLOWING |
| `hunt` `diversity_before/after` | `fsa.diversity_metric(conn)` | SELECT on live alphas table | Yes | FLOWING |
| `grade_one` `status_final` | `corr_failed` | `any(c.get("result") == "FAIL" for c in corr_checks.values())` | Yes — BRAIN response drives it | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 11 phase 3 criterion tests pass | `./venv/bin/python -m pytest test_phase3.py -v` | 11 passed in 0.10s | PASS |
| `classify_from_checks` NEAR logic | Test via pytest (criterion 1 suite, 5 tests) | All 5 PASS | PASS |
| Mutation lineage pre-insert (mock LLM) | Test via pytest (`test_criterion_2_mutation_lineage`) | PASS — stub row with `parent_alpha_id='TEST_MUT_SRC'` and `status='queued'` found in DB | PASS |
| Pearson pre-filter (synthetic PnL) | Test via pytest (`test_criterion_3_pearson_prefilter`) | PASS | PASS |
| FSA cold-start guard | Test via pytest (`test_criterion_4_fsa_mining`) | PASS | PASS |
| `diagnosis` column in DB schema | Test via pytest (`test_criterion_3_db_diagnosis_column`) | PASS | PASS |
| No hardcoded 0.7 in selfcorr.py | `grep -n "0\.7" selfcorr.py` | Only appears in a comment ("NEVER hardcode 0.7") — not as a literal value | PASS |

---

### Probe Execution

No `probe-*.sh` scripts declared or found for this phase. Step 7c: SKIPPED (no probes defined).

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| ITR-01 | 03-01, 03-04 | Editor classify + diagnose/mutate + NEAR status vocab in grade.py | SATISFIED | `editor.py` + `grade.py` hooks A/B + `hunt.py` NEAR persistence |
| ITR-02 | 03-01 | Mutation lineage `parent_alpha_id` at insert time | SATISFIED | `editor.py:294-304` pre-insert + `grade.py:113-127` stub replacement |
| ITR-03 | 03-02, 03-04 | Local selfcorr pre-filter (proxy_gate + is_duplicate_by_pnl) | SATISFIED | `selfcorr.py` all 8 functions + wired into `grade.py` |
| ITR-04 | 03-03, 03-04 | FSA motif mining + filter + diversity metric | SATISFIED | `fsa.py` all 4 functions + wired into `find_alphas.py` and `hunt.py` |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `find_alphas.py` | 266, 277 | `PLACEHOLDER` in thesis prose template | Info | Intentional — these are template strings for human/LLM authoring step (D-03). Not a code stub. |
| `editor.py` | 291 | Comment mentions stub alpha_id prefix convention | Info | Comment only, no code smell. |

No TBD/FIXME/XXX debt markers found in any Phase 3 implementation file.

---

### Human Verification Required

#### 1. Mutation Loop End-to-End (Live BRAIN Session)

**Test:** Run `python hunt.py --max-depth 1 --max-sims 5` against an authenticated BRAIN session where at least one candidate is expected to produce a NEAR/FAIL result.
**Expected:** After Gen 0, at least one alpha is classified NEAR or FAIL; `editor.diagnose_and_mutate` is called; mutations are pre-inserted as `status='queued'` stubs; `grade_many` in Gen 1 simulates those expressions (not skipped as duplicates); `sims_used` increments beyond Gen 0 count; the CR-01 fix is confirmed working end-to-end.
**Why human:** The queued-stub gradable path in `grade_one` (CR-01 fix) can only be exercised when `simulate()` actually runs against the live BRAIN API. No mock can confirm the stub is graded (not rejected) under concurrent-worker conditions.

#### 2. proxy_gate Self-Exclusion Under Real PnL Data

**Test:** With a PASS alpha in the DB that has a `pnl_cache/` file, call `selfcorr.proxy_gate(alpha_id, conn)` where `alpha_id` is its own `alpha_id`.
**Expected:** Returns `False` (allow sim) — the WR-02 self-exclusion (`reference_paths = [p for p in reference_paths if p != parent_pnl_path]`) prevents the parent's own PnL from producing correlation 1.0.
**Why human:** Requires a real `pnl_cache/` directory with actual PnL JSON files. The existing test suite uses synthetic in-memory data and cannot verify the file-path exclusion logic with real cached paths.

#### 3. FSA Diversity Metric Before/After Spread

**Test:** After completing a real `/hunt` run (at least Gen 0 + Gen 1), examine the printed `diversity before/after` output.
**Expected:** `top_motif_share` is a meaningful fraction (not 0.0 from empty PASS set); after FSA filtering, the after share is equal to or lower than before (filter reduces structural concentration).
**Why human:** `diversity_metric` is correct code but its output is only meaningful when real PASS alphas are in the DB. The before/after comparison cannot be verified without live grading results.

---

### Gaps Summary

No automated-verifiable gaps found. All 4 ROADMAP success criteria are VERIFIED in code. The prior critical issues identified in 03-REVIEW.md (CR-01 through CR-06, WR-01 through WR-12) have been resolved in the current codebase as documented in 03-REVIEW-FIX.md, and the fixes are confirmed present in the source files read during this verification.

The 3 human verification items above are behavioral end-to-end checks that require a live BRAIN session and cannot be verified by static analysis or unit tests alone. They do not indicate missing implementation — the implementation is complete — but the mutation loop's correctness under live conditions is the core value proposition of Phase 3 and warrants explicit human confirmation.

---

_Verified: 2026-06-10T09:15:00Z_
_Verifier: Claude (gsd-verifier)_
