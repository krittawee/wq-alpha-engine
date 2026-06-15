---
phase: 06-additivity-gate
verified: 2026-06-15T14:00:00Z
status: passed
score: 15/15
overrides_applied: 0
---

# Phase 6: Additivity Gate — Verification Report

**Phase Goal:** A reusable additivity gate is available that ranks candidates by cheap local PnL correlation (no BRAIN call) and confirms finalists with a real BRAIN correlation check — nothing is presented as submit-ready without passing both layers.
**Verified:** 2026-06-15T14:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `rank_by_proxy()` returns candidates sorted by estimated book correlation using local PnL proxy with zero BRAIN API calls | VERIFIED | `additivity.py:155-230` implements full sort ascending by `combined_corr`; calls only `selfcorr.get_book_pnl_paths` + `selfcorr.get_selfcorr_limit` (SQLite only); test `test_phase6_plan2_rank_by_proxy_zero_brain_calls` mocks `requests.Session` and confirms no HTTP call occurs |
| 2 | `confirm_additive()` calls BRAIN's `/check`, reads SELF_CORRELATION/PROD_CORRELATION from `is.checks`, and returns a verdict using BRAIN's own limits — no hardcoded threshold | VERIFIED | `additivity.py:237-322` calls `grade.trigger_correlation_check` + `grade.poll_correlation`; reads `self_limit = sc.get("limit")` from live response; `grep -n "0\.7" additivity.py` returns no output; test `test_phase6_plan2_confirm_additive_fail_and_no_hardcode` asserts `brain_self_corr_limit == 0.65` (BRAIN-supplied) |
| 3 | Any code path producing a submit recommendation invokes the additivity gate and withholds the recommendation if the gate fails — IS checks alone are not sufficient | VERIFIED | `hunt.py:86-138` defines `_apply_additivity_gate`; `grep -c "_apply_additivity_gate" hunt.py` = 3 (1 def + 2 call sites at lines 313 and 407); `grep -c "_rank_best(all_pass_ids" hunt.py` = 0 (old direct path fully replaced); integration tests `test_phase6_plan3_gate_blocks_nonaddititve` and `test_phase6_plan3_gate_passes_additive` both pass |
| 4 | The same gate structure can be called as a rank-score (float) or yes/no filter (boolean) — reusable in both discovery and refinement | VERIFIED | `AdditivityResult` dataclass at `additivity.py:29-47` carries `combined_corr: Optional[float]` (rank) and `additive: Optional[bool]` + `proxy_drop: bool` (filter); dual API confirmed by spot-check: `r.combined_corr = 0.3`, `r.additive = True`; `CONFIRM_LIMIT` and `PROXY_MARGIN` are named constants allowing reuse from Phase 7 and Phase 9 without modification (stated in module docstring) |

**Score:** 4/4 ROADMAP truths verified

---

### Plan Must-Haves (All Plans)

#### Plan 01 — selfcorr.py primitives

| # | Must-Have Truth | Status | Evidence |
|---|----------------|--------|----------|
| 1 | `get_book_pnl_paths(conn)` returns only `status='ACTIVE'` pnl_paths, never 'pass' or 'UNSUBMITTED' | VERIFIED | `selfcorr.py:307-324` queries `WHERE pnl_path IS NOT NULL AND status='ACTIVE'` only; test `test_phase6_plan1_get_book_pnl_paths_active_only` asserts 'pass' and 'UNSUBMITTED' are excluded |
| 2 | `backfill_active_pnl` no longer silently skips alphas whose pnl_path is set in DB but file is absent | VERIFIED | `selfcorr.py:486-488` calls `n_stale = _null_stale_pnl_paths(conn)` as first statement; test `test_phase6_plan1_backfill_nulls_stale_before_fetch` confirms `get_pnl` called exactly once after stale-null |
| 3 | `_null_stale_pnl_paths` nulls the pnl_path column for rows where the cached file is missing, before the backfill SELECT | VERIFIED | `selfcorr.py:436-460` probes `Path(pnl_path).exists()` for every non-null row, batch-updates stale rows to NULL, commits, returns count; wired at line 486 before SELECT at line 490 |
| 4 | Four `test_phase6_plan1_*` tests pass | VERIFIED | `venv/bin/python -m pytest test_phase4.py -k "phase6_plan1" -q` → `4 passed` |
| 5 | `get_reference_pnl_paths` unchanged (still includes 'pass' for proxy_gate dedup) | VERIFIED | `selfcorr.py:300-303` query still uses `status IN ('pass', 'ACTIVE')` |

#### Plan 02 — additivity.py core module

| # | Must-Have Truth | Status | Evidence |
|---|----------------|--------|----------|
| 6 | `rank_by_proxy` returns candidates sorted ascending by `combined_corr`; missing PnL appended last with `skipped=True` | VERIFIED | `additivity.py:226-230` sorts via key `(combined_corr is None, combined_corr)` ascending then appends `skipped_results`; test `test_phase6_plan2_rank_by_proxy_sort_ascending` and `test_phase6_plan2_missing_pnl_skipped_last` pass |
| 7 | `rank_by_proxy` makes zero BRAIN API calls | VERIFIED | Only calls `selfcorr.get_book_pnl_paths`, `selfcorr.get_selfcorr_limit`, and `selfcorr.max_pearson` (all local SQLite/file reads); test `test_phase6_plan2_rank_by_proxy_zero_brain_calls` mocks `requests.Session.get` and asserts `call_count == 0` |
| 8 | Soft pre-filter sets `proxy_drop=True` only when `combined_corr > limit + PROXY_MARGIN`; when limit is None, never dropped | VERIFIED | `additivity.py:212-215` implements exact condition; test `test_phase6_plan2_soft_prefilter_margin` asserts correct behavior at 0.78 vs 0.72 and limit=None |
| 9 | `confirm_additive` reads `c['limit']` from BRAIN's live `/check` response, never from DB; returns `AdditivityResult` with `additive=True/False/None` | VERIFIED | `additivity.py:292-307` reads `self_limit = sc.get("limit")` exclusively; no 0.7 literal; test 9 asserts `brain_self_corr_limit == 0.65` roundtrip from mocked response |
| 10 | `AdditivityResult` serves as both float rank (`combined_corr`) and bool filter (`additive`, `proxy_drop`) — ADD-04 dual API | VERIFIED | Dataclass definition at lines 29-47; spot-check confirms both attributes accessible |
| 11 | Nine `test_phase6_plan2_*` tests pass | VERIFIED | `venv/bin/python -m pytest test_phase4.py -k "phase6_plan2" -q` → `9 passed` |

#### Plan 03 — hunt.py gate wiring

| # | Must-Have Truth | Status | Evidence |
|---|----------------|--------|----------|
| 12 | No alpha labeled `best_submittable` unless `confirm_additive` returns `additive=True` — gate enforced at both assignment sites | VERIFIED | `hunt.py:313` and `hunt.py:407` both call `_apply_additivity_gate`; inside that helper (line 133): `if result.additive is True` (strict — None and False excluded); `grep -c "_rank_best(all_pass_ids" hunt.py` = 0 |
| 13 | When `all_pass_ids` is empty, gate returns None (no error) | VERIFIED | `hunt.py:90-92`: `if not all_pass_ids: return None` guard present |
| 14 | When all proxy survivors have `additive=False` or `additive=None`, `best_submittable` is None | VERIFIED | `hunt.py:135-136`: `if not confirmed_ids: print(...); return None` after the confirm loop; test `test_phase6_plan3_gate_blocks_nonaddititve` asserts result is None |
| 15 | Two integration tests pass: `test_phase6_plan3_gate_blocks_*` and `test_phase6_plan3_gate_passes_additive` | VERIFIED | `venv/bin/python -m pytest test_phase4.py -k "phase6_plan3" -q` → `2 passed` |

**Score:** 15/15 must-have truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `selfcorr.py` | `get_book_pnl_paths` + `_null_stale_pnl_paths` + backfill fix | VERIFIED | All three present at lines 307-324, 436-460, 486-488; substantive implementations |
| `additivity.py` | `AdditivityResult`, `PROXY_MARGIN`, `CONFIRM_LIMIT`, `_combined_book_corr`, `rank_by_proxy`, `confirm_additive` | VERIFIED | 323-line module; all named exports present; imports cleanly |
| `hunt.py` | `import additivity` + `_apply_additivity_gate` at both `best_submittable` sites | VERIFIED | Import at line 30; helper defined lines 86-138; called at lines 313 and 407 |
| `test_phase4.py` | 15 offline phase 6 tests (4 plan1 + 9 plan2 + 2 plan3) | VERIFIED | `venv/bin/python -m pytest test_phase4.py -k "phase6" -q` → `15 passed` |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `additivity.rank_by_proxy` | `selfcorr.get_book_pnl_paths` | `selfcorr.get_book_pnl_paths(conn)` | WIRED | `additivity.py:174` |
| `additivity._combined_book_corr` | `selfcorr._pnls_to_daily_returns`, `selfcorr._pearson` | direct call | WIRED | `additivity.py:107, 139, 148` |
| `additivity.confirm_additive` | `grade.trigger_correlation_check`, `grade.poll_correlation` | `import grade` | WIRED | `additivity.py:270, 274` |
| `hunt._apply_additivity_gate` | `additivity.rank_by_proxy` | `additivity.rank_by_proxy(pass_candidates, conn)` | WIRED | `hunt.py:120` |
| `hunt._apply_additivity_gate` | `additivity.confirm_additive` | `additivity.confirm_additive(client, r.alpha_id, conn)` | WIRED | `hunt.py:130` |
| `hunt._apply_additivity_gate` | `additivity.CONFIRM_LIMIT` | `proxy_survivors[:additivity.CONFIRM_LIMIT]` | WIRED | `hunt.py:125` |
| `selfcorr.backfill_active_pnl` | `selfcorr._null_stale_pnl_paths` | called as first statement | WIRED | `selfcorr.py:486` |

---

### Data-Flow Trace (Level 4)

`additivity.rank_by_proxy` depends on PnL files on disk and SQLite:
- `get_book_pnl_paths(conn)` queries SQLite for ACTIVE pnl_paths
- `_combined_book_corr` reads PnL JSON files from those paths
- The `_null_stale_pnl_paths` fix ensures stale DB entries are cleared before backfill, so `get_book_pnl_paths` returns real cached paths after backfill runs

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `additivity.rank_by_proxy` | `ref_paths` | `selfcorr.get_book_pnl_paths(conn)` → SQLite `SELECT WHERE status='ACTIVE'` | Yes — real DB query | FLOWING |
| `additivity.confirm_additive` | `corr_checks` | `grade.poll_correlation` → BRAIN `/check` response | Yes — live BRAIN call | FLOWING |
| `selfcorr.backfill_active_pnl` | rows to fetch | `_null_stale_pnl_paths` → SELECT WHERE pnl_path IS NULL | Yes — DB rows after stale-null | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full phase 6 test suite (15 tests) | `venv/bin/python -m pytest test_phase4.py -k "phase6" -q` | 15 passed, 0 failed | PASS |
| Full regression suite (48 tests) | `venv/bin/python -m pytest test_phase4.py -q` | 48 passed, 18 warnings (deprecation only), 0 failed | PASS |
| `AdditivityResult` dual API importable | `venv/bin/python -c "import additivity; r = additivity.AdditivityResult(..., combined_corr=0.3, additive=True); print(r.combined_corr, r.additive)"` | `0.3 True` | PASS |
| No hardcoded 0.7 threshold | `grep -n "0\.7" additivity.py` | no output | PASS |
| Old gate bypass pattern gone | `grep -c "_rank_best(all_pass_ids" hunt.py` | `0` | PASS |
| New gate present at both sites | `grep -c "_apply_additivity_gate" hunt.py` | `3` | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| ADD-01 | Plans 01, 02 | System estimates candidate correlation to user's book from cheap local PnL proxy | SATISFIED | `additivity.rank_by_proxy` + `selfcorr.get_book_pnl_paths` implement zero-BRAIN-call proxy correlation; 13 offline tests verify |
| ADD-02 | Plan 02 | System confirms finalist's additivity with BRAIN's real correlation check | SATISFIED | `additivity.confirm_additive` calls `grade.trigger_correlation_check` + `grade.poll_correlation`; reads live `c["limit"]`; no hardcoded threshold |
| ADD-03 | Plan 03 | No alpha presented as submit-ready without passing the additivity gate | SATISFIED | `hunt._apply_additivity_gate` replaces both `_rank_best(all_pass_ids, conn)` call sites; `grep -c` confirms 0 old pattern, 3 new pattern occurrences |
| ADD-04 | Plans 02, 03 | Gate is reusable as yes/no filter (discovery) and rank-by score (refinement) | SATISFIED | `AdditivityResult.combined_corr` (float rank) + `AdditivityResult.additive` / `proxy_drop` (bool filter); module docstring states reusability by Phase 7 and Phase 9 |

All four REQUIREMENTS.md phase-6 requirements (ADD-01 through ADD-04) are satisfied.

---

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `grade.py:358` | `datetime.datetime.utcnow()` deprecated | Info | Deprecation warning only; not introduced by this phase; pre-existing; not a blocker |

No TBD, FIXME, XXX, or TODO markers in any phase-6-modified file. No stub implementations. No hardcoded thresholds.

---

### Probe Execution

No probe scripts declared for this phase. Step 7c: SKIPPED (no probe-*.sh files declared in plans or found in scripts/).

---

### Human Verification Required

None. All behavioral claims are verifiable offline via the test suite. The `confirm_additive` BRAIN-live path is fully covered by mocks in the offline tests, and the mock tests assert the exact limit-reading behavior (`brain_self_corr_limit == 0.65` from a mocked response with `"limit": 0.65`) confirming no hardcode is possible.

---

## Gaps Summary

No gaps. All 4 ROADMAP success criteria and all 15 plan-level must-have truths are VERIFIED by direct code reading and test execution. The phase goal is achieved.

---

_Verified: 2026-06-15T14:00:00Z_
_Verifier: Claude (gsd-verifier)_
