---
phase: 06-additivity-gate
reviewed: 2026-06-15T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - additivity.py
  - selfcorr.py
  - hunt.py
  - test_phase4.py
findings:
  critical: 1
  warning: 6
  info: 4
  total: 11
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-06-15T00:00:00Z
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Reviewed the Phase 6 additivity-gate changes: the new `additivity.py` module
(`rank_by_proxy` / `confirm_additive` / `_combined_book_corr`), the two
`selfcorr.py` primitives (`get_book_pnl_paths`, `_null_stale_pnl_paths`), and the
`hunt.py` wiring (`_apply_additivity_gate`). Tests in `test_phase4.py` were
reviewed for reliability, not flagged for style.

The core logic is mostly sound and well-tested, but there is one BLOCKER that
violates the project's most important constraint (BRAIN call budget / throttle
risk): `_apply_additivity_gate` re-runs the live BRAIN `/check` on the *entire
accumulated* PASS set on every generation and again in the final pass, with no
caching and no `max_sims` accounting. This can fire many more BRAIN `/check`
calls than `CONFIRM_LIMIT` advertises and is not counted against the sim budget.
Several warnings concern silent inclusion of no-data candidates in the confirm
finalist slots, an unused import, and a docstring/behavior mismatch.

## Critical Issues

### CR-01: Additivity gate re-confirms the entire accumulated PASS set every generation — uncounted BRAIN /check calls, throttle risk

**File:** `hunt.py:313`, `hunt.py:407`, `hunt.py:124-132`
**Issue:**
`_apply_additivity_gate(client, all_pass_ids, conn)` is called once at the end of
*every* generation (line 313) and again in the final pass (line 407). It is
always passed `all_pass_ids`, which is the **accumulated** list of PASS alpha_ids
across all generations (`all_pass_ids.extend(pass_ids)` at line 312).

Inside `_apply_additivity_gate`, `confirm_additive` — which performs a real BRAIN
`GET /alphas/{id}/check` plus a polling loop (up to `timeout=300s`) — is called on
the first `CONFIRM_LIMIT` (=3) proxy survivors with no memoization
(`hunt.py:125-130`). Because the same PASS alphas persist in `all_pass_ids` across
generations, the *same* finalists are re-confirmed on each generation and once
more in the final pass.

Consequences, all of which hit CLAUDE.md hard constraints:
1. **Budget violation:** `confirm_additive` BRAIN calls are never added to
   `sims_used` and are never checked against `max_sims`. The "hard sim ceiling"
   (D-17) does not bound them. A run with `max_depth=2` can issue up to
   `3 (Gen 0 loop) + 3 (Gen 1 loop) + 3 (final pass) = 9` correlation checks for
   the same 3 alphas.
2. **Throttle / slot risk:** Each `/check` drives a polling loop that can run for
   minutes. CLAUDE.md caps concurrent BRAIN work at ≤3 on the shared session and
   warns about throttling; spraying redundant `/check` calls per generation is
   exactly the waste the project is built to avoid ("time, not money, is the
   bottleneck").
3. **Comment is misleading:** the docstring claims "T-06-12: CONFIRM_LIMIT caps
   the worst-case BRAIN /check cost per run" — but CONFIRM_LIMIT caps cost *per
   invocation*, and the gate is invoked O(generations) times, so the per-run cost
   is `CONFIRM_LIMIT × (max_depth + 1)`, not `CONFIRM_LIMIT`.

**Fix:** Confirm each alpha at most once per run, and only confirm at the end.
Cache confirmation results keyed by alpha_id, and/or run the gate a single time
after the loop completes instead of every generation:

```python
# In hunt(): drop the per-generation gate call at line 313.
# Compute best_submittable once after the loop, over all_pass_ids.

# In _apply_additivity_gate(): memoize confirmations so re-invocation is free.
_CONFIRM_CACHE: dict = {}  # module-level, keyed by alpha_id

def _apply_additivity_gate(client, all_pass_ids, conn):
    ...
    for r in proxy_survivors[:additivity.CONFIRM_LIMIT]:
        if r.alpha_id in _CONFIRM_CACHE:
            result = _CONFIRM_CACHE[r.alpha_id]
        else:
            result = additivity.confirm_additive(client, r.alpha_id, conn)
            _CONFIRM_CACHE[r.alpha_id] = result
        if result.additive is True:
            confirmed_ids.append(r.alpha_id)
    ...
```

Additionally, the confirm count should be accounted for so it cannot silently
exceed the intended BRAIN budget.

## Warnings

### WR-01: No-data / proxy-failed candidates consume confirm finalist slots

**File:** `hunt.py:121-130`, `additivity.py:202`, `additivity.py:228`
**Issue:**
`proxy_survivors = [r for r in ranked if not r.proxy_drop]` keeps every candidate
that was not hard-dropped — including candidates whose `combined_corr is None`
(book reference set empty, insufficient overlap, or PnL unreadable). The sort at
`additivity.py:228` pushes `combined_corr is None` items *after* scored items, but
`skipped` candidates (also `proxy_drop=False`) are appended at the very end and
are still survivors. When few scored candidates exist, these no-data candidates
fill the `[:CONFIRM_LIMIT]` finalist slots and trigger real BRAIN `/check` calls
(see the `combined_corr is None` branch explicitly handled at `hunt.py:128-129`),
spending the scarce BRAIN budget on alphas the proxy could not even rank.

**Fix:** Exclude unranked candidates from the confirm finalists, or rank them
strictly last and only confirm them if no scored survivor exists:

```python
proxy_survivors = [
    r for r in ranked
    if not r.proxy_drop and not r.skipped and r.combined_corr is not None
]
```

### WR-02: `additive=None` (inconclusive) silently dropped without surfacing to caller

**File:** `hunt.py:131-138`, `additivity.py:301-307`
**Issue:**
`confirm_additive` can return `additive=None` on a TimeoutError or when
`SELF_CORRELATION` is absent from BRAIN's response (`additivity.py:282-286`,
`301-303`). The gate treats `None` as non-additive (`if result.additive is True`)
and, if no candidate confirms, returns `None` so `best_submittable=None`. That is
the safe direction, but a run where every finalist *timed out* is indistinguishable
from a run where every finalist was genuinely non-additive — the user is told
"no confirmed-additive candidates" (`hunt.py:135`) and the PASS alphas are
effectively discarded. A timeout is a transient BRAIN condition, not a verdict.

**Fix:** Track inconclusive results separately and surface them (e.g., log the
count of `additive is None` finalists and/or include them in the returned dict so
the caller can retry), rather than collapsing timeout and rejection into the same
"none additive" message.

### WR-03: `_combined_book_corr` sums raw daily returns across book alphas without weighting — proxy can misrank

**File:** `additivity.py:110-111`
**Issue:**
The combined book series is built as a plain sum of each reference alpha's daily
*returns* (`book_map[date] += ret`). BRAIN's real self-correlation is computed
against each submitted alpha individually (and the team book is a weighted/booksize
combination), not a naive unweighted sum of raw PnL deltas. Reference alphas with
larger PnL magnitudes (e.g., different booksize scaling) dominate the sum, so the
proxy can rank a candidate as "additive" when it is actually highly correlated to
one large book member. The proxy is advisory (a real `/check` follows), but a
mis-ranked proxy can push the genuinely-additive candidate past the `CONFIRM_LIMIT`
finalist cutoff so it never gets confirmed.

**Fix:** Normalize each reference's daily returns (e.g., z-score or divide by its
own stdev) before summing, or correlate the candidate against each reference and
aggregate (max/mean) as `max_pearson` already does — matching the intent of
predicting BRAIN's per-alpha self-corr gate. At minimum, document that the sum is
an unweighted approximation and that `max_pairwise_corr` is the more faithful gate
predictor.

### WR-04: `proxy_drop` uses combined-book correlation but BRAIN's self-corr gate is pairwise

**File:** `additivity.py:212`
**Issue:**
The hard pre-filter drops a candidate when `combined_corr > limit + margin`, where
`combined_corr` is correlation against the *summed* book. But BRAIN's
`SELF_CORRELATION` limit (read via `get_selfcorr_limit`) is a *pairwise* threshold
against individual alphas. Comparing a combined-book correlation against a pairwise
limit is an apples-to-oranges comparison: a candidate can have low pairwise
correlation to every individual book alpha yet a high combined-book correlation
(or vice versa), causing both false drops and false survivals. `max_pairwise_corr`
is already computed (line 206) and is the metric that actually maps onto the
`SELF_CORRELATION` limit.

**Fix:** Gate `proxy_drop` on `max_pairwise_corr` (the pairwise quantity that
matches BRAIN's pairwise limit), and keep `combined_corr` purely as the additivity
*rank* key:

```python
if (max_pairwise_corr is not None and limit is not None
        and max_pairwise_corr > limit + margin):
    proxy_drop = True
```

### WR-05: `confirm_additive` accepts PASS without consulting PROD_CORRELATION even when present

**File:** `additivity.py:299-307`
**Issue:**
The verdict is derived from `SELF_CORRELATION` only. The docstring justifies this
because `PROD_CORRELATION` is "optional" and "its absence is not an error." That is
correct for *absence* — but when `PROD_CORRELATION` *is* present and returns
`FAIL`, the alpha would still be marked `additive=True`. `prod_result` is parsed
and stored (`additivity.py:297`, `320`) but never affects the verdict, so a
PROD-correlation failure is silently ignored for additivity purposes.

**Fix:** Treat a present-and-FAILing `PROD_CORRELATION` as non-additive:

```python
if self_result is None:
    additive = None
elif self_result == "PASS" and prod_result in (None, "PASS", "PENDING"):
    additive = True
else:
    additive = False
```

(Confirm with the BRAIN check semantics whether a `PROD_CORRELATION` FAIL should
block additivity; if intentional, document why it is ignored.)

### WR-06: `math` imported but unused in additivity.py

**File:** `additivity.py:8`
**Issue:**
`import math` is present but `math` is never referenced anywhere in
`additivity.py` (all numeric work is delegated to `selfcorr._pearson` /
`_pnls_to_daily_returns`). Dead import.

**Fix:** Remove `import math` from `additivity.py`.

## Info

### IN-01: `total_refs`/`refs_used` warning path cannot warn when all refs fail

**File:** `additivity.py:116-123`
**Issue:**
The "some references skipped" warning at line 116 only fires when
`refs_used < total_refs and refs_used > 0`. When *every* reference fails to load
(`refs_used == 0`), control reaches line 121 and prints the "zero book references"
warning instead — which is fine — but the partial-skip branch never reports the
count of failures in the all-failed case. Minor observability gap; the function
still returns `None` correctly.

**Fix:** Optional — include the skipped count in the zero-reference warning too.

### IN-02: Magic numbers `61` / `60` for minimum overlap are unexplained constants

**File:** `additivity.py:134`, `additivity.py:145`, `selfcorr.py:162`
**Issue:**
The minimum-overlap thresholds (`< 61`, `< 60`) are inline literals with the
rationale only in a comment. `selfcorr._date_overlap_returns` uses `60` and
`_combined_book_corr` uses `61` for the same conceptual "need 60 daily returns"
requirement. The off-by-one difference is intentional (cumulative→daily costs one
point) but easy to break on edit.

**Fix:** Hoist to a named module constant (e.g., `MIN_DAILY_RETURNS = 60`) and
derive the `61` from it, so the two files cannot drift.

### IN-03: `db_path` parameter of `backfill_active_pnl` is unused

**File:** `selfcorr.py:466`, `selfcorr.py:480-481`
**Issue:**
`backfill_active_pnl(..., db_path="alpha_kb.db", ...)` documents `db_path` as
"informational, connection already open" and never uses it. A dead parameter
invites callers to assume it changes behavior.

**Fix:** Remove the parameter, or use it for the documented logging only.

### IN-04: `confirm_additive` does not persist its verdict — re-runs are pure cost

**File:** `additivity.py:309-322`
**Issue:**
`confirm_additive` returns an `AdditivityResult` but writes nothing to the DB
(unlike `fetch_and_cache_pnl`, which caches). Combined with CR-01, every
re-invocation re-incurs the BRAIN cost because there is no persisted record of a
prior verdict. Even after CR-01 is fixed with an in-memory cache, the verdict is
lost across process restarts.

**Fix:** Persist the brain_self_corr / additive verdict (e.g., into `checks` or a
dedicated column) so subsequent `/hunt` or `/iterate` runs can skip already-checked
alphas. Reusability across Phase 7/9 (per the module docstring) depends on this.

---

_Reviewed: 2026-06-15T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
