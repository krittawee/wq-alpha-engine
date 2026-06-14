---
phase: 03-smart-iteration
plan: "04"
subsystem: grading-pipeline, generation-pipeline
tags: [wiring, integration, selfcorr, fsa, grade, find_alphas]
dependency_graph:
  requires:
    - 03-01  # editor.py
    - 03-02  # selfcorr.py
    - 03-03  # fsa.py
  provides:
    - grade.py with parent_alpha_id lineage + Hook A (proxy_gate) + Hook B (selfcorr filter)
    - find_alphas.py with FSA mine+filter + avoid-list injection into researcher thesis
    - researcher.build_thesis with avoid_motifs param and LLM steer injection
  affects:
    - 03-05  # hunt loop wires grade_one(parent_alpha_id=...) for mutations
    - 03-06  # editor reclassifies after grading; find_alphas provides filtered candidates
tech_stack:
  added: []
  patterns:
    - pre-sim proxy gate (Hook A): selfcorr.proxy_gate before _simulate_to_alpha for mutations
    - post-sim local duplicate filter (Hook B): selfcorr.fetch_and_cache_pnl + is_duplicate_by_pnl after IS survivor, before trigger_correlation_check
    - FSA candidate filter: fsa.mine_frequent_motifs + filter_candidates in find_alphas generation path
    - upstream LLM steer: avoid_motifs injected into researcher.build_thesis cited_insights
key_files:
  modified:
    - grade.py
    - find_alphas.py
    - researcher.py
decisions:
  - avoid_motifs injected into cited_insights (not a separate thesis dict key used by ideator) so the LLM prose layer sees the avoid-list in a human-readable format
  - Hook B early-return omits status writing to DB for Hook A (proxy_gate filtered, no alpha_id to write against); Hook B writes status='duplicate' to DB because alpha was already persisted via upsert_alpha in Step 6
  - build_thesis passes avoid_motifs through in the returned dict for any downstream consumer
metrics:
  duration: "~10 minutes"
  completed: "2026-06-10"
  tasks_completed: 2
  files_modified: 3
---

# Phase 3 Plan 04: Integration Wiring — grade.py + find_alphas.py Summary

Surgical wiring of the three Wave 1 modules (editor.py, selfcorr.py, fsa.py) into the existing
grade.py and find_alphas.py pipelines. No new logic was created — all logic lives in plans 01-03.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | grade.py — NEAR status vocab + parent_alpha_id param + selfcorr hooks | 998ca73 | grade.py |
| 2 | find_alphas.py — FSA filter + avoid-list injection; researcher.py — avoid_motifs param | fa42c11 | find_alphas.py, researcher.py |

## What Was Built

**grade.py (Task 1):**
- Added `import selfcorr` at module top
- Updated `grade_one` signature: `grade_one(client, conn, expression, run_id, parent_alpha_id=None)` — backward compatible for all existing callers
- `parent_alpha_id` written into `alpha_dict` so lineage is persisted via `db.upsert_alpha`
- **Hook A (proxy_gate):** Before Step 2 simulate — for mutations (`parent_alpha_id is not None`), calls `selfcorr.proxy_gate(parent_alpha_id, conn)`. Returns `{"status": "duplicate", "alpha_id": None}` immediately if parent too correlated. No DB write (no alpha_id to write against). Gracefully degrades: proxy_gate returns False on missing PnL, allowing sim to proceed.
- **Hook B (selfcorr filter):** After IS survivor check, before `trigger_correlation_check`. Calls `selfcorr.fetch_and_cache_pnl`, then `selfcorr.is_duplicate_by_pnl` against reference paths. If locally duplicate: writes `status='duplicate'` to DB, returns early — skipping BRAIN POST /check entirely. Gracefully degrades: if fetch returns None, falls through to `trigger_correlation_check` as before.
- `grade_many`, `trigger_correlation_check`, `poll_correlation`, and `MAX_CONCURRENT_SIMS` unchanged.

**find_alphas.py (Task 2):**
- Added `import fsa`
- Restructured `find_alphas()` order: `mine_frequent_motifs` → `build_thesis(avoid_motifs)` → `generate_candidates` → `filter_candidates` → `queueable`
- FSA mining placed before `build_thesis` so avoid-list is ready for LLM steer at thesis generation time
- `fsa.filter_candidates` applied after `generate_candidates`, before `queueable` — drops candidates that share frequent motifs
- Prints FSA filter stats when candidates are dropped (avoid_motifs non-empty)
- Human-stop behavior preserved: no grading called (D-02 LOCKED)

**researcher.py (Task 2):**
- Updated `build_thesis(conn, archetype=None, avoid_motifs=None)` — backward compatible default
- When `avoid_motifs` non-empty: appends a "Structural motifs to AVOID" insight to `cited_insights` for upstream LLM steer (D-15)
- `avoid_motifs` passed through in returned thesis dict as `avoid_motifs: []` when None

## Deviations from Plan

None — plan executed exactly as written.

The plan specified avoid_motifs injection "into the prompt/context" for researcher. Since researcher.py has no LLM call (it's the deterministic layer), the natural injection point is `cited_insights` — the structured output read by the LLM prose layer downstream. This matches "wording is Claude's discretion" per 03-CONTEXT.md §Claude's Discretion.

## Known Stubs

None. All wiring is complete and functional. No placeholder data flows.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced. Hook B calls `selfcorr.fetch_and_cache_pnl` which uses the same BRAIN session as all other grade calls — no new trust boundary. Covered by T-03-10 and T-03-13 in plan threat model.

## Self-Check: PASSED

All files verified present: grade.py, find_alphas.py, researcher.py, 03-04-SUMMARY.md.
All commits verified in git log: 998ca73, fa42c11.
