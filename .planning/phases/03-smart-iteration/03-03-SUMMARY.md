---
phase: "03-smart-iteration"
plan: "03"
subsystem: "fsa"
tags: ["ast", "motif-mining", "diversity", "structural-avoidance", "cold-start"]
dependency_graph:
  requires: []
  provides: ["fsa.extract_abstract_subtrees", "fsa.mine_frequent_motifs", "fsa.filter_candidates", "fsa.diversity_metric"]
  affects: ["find_alphas.py (plan 04)", "hunt.py (plan 05)"]
tech_stack:
  added: []
  patterns: ["stdlib ast mode='eval' for safe expression parsing", "Counter-based motif frequency aggregation", "per-alpha set deduplication before counting"]
key_files:
  created:
    - fsa.py
  modified: []
decisions:
  - "DEFAULT_THRESHOLD=0.5: motif must appear in 50%+ of PASS alphas to be flagged (Claude's discretion per 03-CONTEXT.md)"
  - "DEFAULT_MIN_SAMPLES=5: cold-start guard — return [] when fewer than 5 PASS alphas exist"
  - "Diversity metric counts per-occurrence (not per-alpha) for top_motif_share — provides concentration signal for ROADMAP criterion 4"
  - "filter_candidates degrades gracefully: keeps candidate if extract_abstract_subtrees raises unexpectedly"
metrics:
  duration: "~10 minutes"
  completed: "2026-06-10T02:22:19Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 0
---

# Phase 3 Plan 03: FSA (Frequent Subtree Avoidance) Summary

## One-Liner

AST-based structural motif mining from PASS alphas using stdlib ast, with cold-start guard, frequency threshold filter, and diversity metric for ROADMAP criterion 4.

## What Was Built

`fsa.py` — a stdlib-only module that mines abstract operator-shape motifs from PASS alphas
and provides a filter function to prevent the autonomous loop from re-discovering the same
structural families.

### Exports

| Function | Purpose |
|----------|---------|
| `extract_abstract_subtrees(expr)` | Parses FastExpr via `ast.parse(mode='eval')`, returns operator-shape motif strings like `"ts_rank(FIELD,NUM)"`. Returns `[]` on SyntaxError (ternary safety). |
| `mine_frequent_motifs(conn, threshold, min_samples)` | Returns motifs appearing in >= threshold fraction of PASS alphas. Returns `[]` below min_samples (cold-start guard). Queries only `status='pass'`. |
| `filter_candidates(candidates, avoid_motifs)` | Drops candidate dicts whose expression contains any motif in the avoid list. No-op when avoid_motifs is empty. |
| `diversity_metric(conn)` | Read-only metric for ROADMAP criterion 4: pass_alpha_count, unique_motifs, top_motif, top_motif_share. |

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | AST subtree extraction and frequency mining | 8b5fa5d | fsa.py (created, all 4 exports) |
| 2 | filter_candidates and diversity metric helper | 8b5fa5d | fsa.py (included in Task 1 commit — single file) |

## Verification Results

All automated verifications passed:
- `extract_abstract_subtrees("ts_rank(close, 5)")` returns `["ts_rank(FIELD,NUM)"]`
- `extract_abstract_subtrees("rank(ts_mean(close,20))")` returns `["rank(CALL)", "ts_mean(FIELD,NUM)"]`
- `extract_abstract_subtrees("close ? open : high")` returns `[]` (ternary safety)
- `mine_frequent_motifs(conn)` returns `[]` with 2 PASS alphas (cold-start guard active, min_samples=5)
- `filter_candidates(cands, [])` is a no-op
- `filter_candidates(cands, ["ts_rank(FIELD,NUM)"])` drops matching candidate
- `diversity_metric(conn)` returns correct dict structure with pass_alpha_count, unique_motifs, top_motif, top_motif_share
- `import fsa` — clean import, stdlib-only

## Deviations from Plan

None — plan executed exactly as written. Both tasks were implemented in a single `fsa.py`
write since they form one cohesive module. Task 2 functions were included in the Task 1
commit (single file, both tasks cover the same file).

## Known Stubs

None. All functions are fully implemented and wired to the DB. No hardcoded or placeholder values.

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes introduced.
`fsa.py` uses `ast.parse(mode='eval')` which is read-only (no exec/eval) and wraps SyntaxError.
SQL queries are parameterized selects on trusted local DB. T-03-08, T-03-09, T-03-SC mitigated as planned.

## Self-Check

- [x] fsa.py exists at worktree root
- [x] commit 8b5fa5d exists in git log
- [x] All 4 exports present: extract_abstract_subtrees, mine_frequent_motifs, filter_candidates, diversity_metric
- [x] SUMMARY.md created at .planning/phases/03-smart-iteration/03-03-SUMMARY.md
