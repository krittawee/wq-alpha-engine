---
phase: 01-mvp-grading-engine
plan: "02"
subsystem: sync-layer
tags: [sync, catalog, brain-api, paginated, sqlite, requests]
dependency_graph:
  requires: [db.init_db, db.upsert_operators, db.upsert_datafields, db.upsert_alpha]
  provides: [sync.sync_all, sync.sync_operators, sync.sync_datafields, sync.sync_existing_alphas]
  affects: [validate.py, grade.py, cli.py]
tech_stack:
  added: []
  patterns: [hand-written-session-calls, offset-limit-pagination, raise-for-status-propagation, standalone-main-guard]
key_files:
  created: [sync.py]
  modified: []
decisions:
  - "dataset field in datafields rows: BRAIN may nest dataset as a dict {id: ...}; sync_datafields unwraps .get('id', dataset_id) for both shapes"
  - "expression field for existing alphas: BRAIN exposes alpha expression under 'regular' key (SDK pattern); fallback to 'expression' key for future-proofing"
  - "login() import deferred to __main__ guard only — sync functions never import login at module level to enforce the no-re-auth-in-loop constraint"
metrics:
  duration: "480 seconds"
  completed_date: "2026-06-07T02:10:00Z"
  tasks_completed: 1
  tasks_total: 1
  files_created: 1
  files_modified: 0
---

# Phase 01 Plan 02: Catalog + Existing-Alpha Sync (sync.py) Summary

## One-Liner

Paginated BRAIN catalog sync (operators + data-fields) and existing-alpha seeder via hand-written client._session calls with immediate 401 propagation.

## What Was Built

`sync.py` pulls BRAIN's catalog and existing alphas into `alpha_kb.db`. It exposes four functions:

- `sync_operators(client, conn)` — `GET /operators`, normalizes operator dicts to `{name, category, definition, signature}`, upserts via `db.upsert_operators`. Returns row count.
- `sync_datafields(client, conn, dataset_id, region, universe, delay)` — paginated `GET /data-fields` with `limit=200/offset` loop. Handles nested `dataset` dict shape from BRAIN. Upserts each page immediately for memory efficiency. Returns total count.
- `sync_existing_alphas(client, conn)` — paginated `GET /alphas` with `limit=100/offset` loop. Maps BRAIN's alpha JSON (`id`, `regular`, `settings`, `is.*`, `dateCreated`) to the locked `alphas` table schema. Seeds self-correlation memory. Returns total count.
- `sync_all(client, conn)` — calls all three in order; prints `[sync] complete`.

`__main__` guard allows `python sync.py` as a standalone catalog refresh command.

All HTTP calls use `client._session.get(...)` followed by `r.raise_for_status()`. A 401 propagates immediately — no catch, no retry. BIOMETRICS_THROTTLED 429 handling mirrors `wq_login.py` convention.

## Tasks

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | Implement sync.py with catalog and existing-alpha sync | Done | 3e78294 |

## Verification Results

- Structure check: STRUCTURE CHECK PASSED
- `grep -c "raise_for_status" sync.py`: 5 (>= 3 required)
- `grep -c "offset" sync.py`: 6 (>= 2 required)
- `python -c "import sync; print('import ok')"`: import ok
- `login()`/`.authenticate()` in sync function bodies: 0 — only in `__main__` guard
- `db.upsert_operators`, `db.upsert_datafields`, `db.upsert_alpha` all called: confirmed

## Deviations from Plan

None — plan executed exactly as written.

Two minor implementation choices within Claude's discretion (noted in plan's action block):
- BRAIN's `dataset` field in `/data-fields` response may be a nested dict `{id: ...}` rather than a plain string. `sync_datafields` unwraps both shapes defensively with `.get('id', dataset_id)`.
- BRAIN's existing alpha JSON exposes the expression under the `regular` key (consistent with the SDK's `simulate()` payload shape). `sync_existing_alphas` reads `alpha.get("regular", "")` with fallback to `alpha.get("expression", "")` for robustness.

## Known Stubs

None. All four functions are fully implemented and wired to `db.*` upsert calls.

## Threat Flags

No new threat surface beyond the plan's threat model.

- T-02-01 (Information Disclosure): print statements output only counts and status messages — no tokens, emails, passwords, or raw API bodies are printed. Mitigated.
- T-02-03 (Spoofing / 401 handling): `raise_for_status()` propagates on every HTTP call — no catch + re-auth path exists in any sync function. Mitigated.

## Self-Check: PASSED

- sync.py exists: FOUND at /Users/winter.__.kor/quant/sync.py (worktree path)
- Commit 3e78294 exists: FOUND
- STRUCTURE CHECK PASSED in verification run
- raise_for_status count = 5 (>= 3): confirmed
- offset count = 6 (>= 2): confirmed
- import ok: confirmed
- login() only in __main__ guard: confirmed
