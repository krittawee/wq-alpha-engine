---
phase: 01-mvp-grading-engine
plan: "01"
subsystem: data-layer
tags: [sqlite, crud, schema, data-layer]
dependency_graph:
  requires: []
  provides: [db.init_db, db.upsert_alpha, db.upsert_checks, db.upsert_operators, db.upsert_datafields, db.expr_exists]
  affects: [sync.py, validate.py, grade.py, cli.py]
tech_stack:
  added: []
  patterns: [sqlite3-wal-mode, insert-or-replace, executemany-bulk-upsert, module-level-init]
key_files:
  created: [db.py]
  modified: []
decisions:
  - "WAL journal mode enabled in init_db for concurrent read safety without extra dependencies"
  - "Column order in _ALPHA_COLS list mirrors schema definition order for maintainability"
  - "limit key from BRAIN is.checks mapped to limit_val column in executemany (avoids SQL reserved word)"
metrics:
  duration: "93 seconds"
  completed_date: "2026-06-07T01:58:20Z"
  tasks_completed: 1
  tasks_total: 1
  files_created: 1
  files_modified: 0
---

# Phase 01 Plan 01: SQLite Data Layer (db.py) Summary

## One-Liner

SQLite CRUD layer with WAL mode, locked 5-table schema, and 6 typed functions (init/upsert/dedupe) using Python stdlib only.

## What Was Built

`db.py` is the foundational data layer for `alpha_kb.db`. It exposes:

- `init_db(path)` — connects, enables WAL, applies all 5 table DDL statements + 2 indexes via `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`, returns the open connection
- `upsert_alpha(conn, alpha_dict)` — `INSERT OR REPLACE INTO alphas` using all 26 columns from the locked schema
- `upsert_checks(conn, alpha_id, checks_list)` — bulk `executemany` mapping BRAIN's `is.checks` array (translates the `limit` key to the `limit_val` column to avoid the SQL reserved word)
- `upsert_operators(conn, rows)` — bulk `executemany` into `operators` table
- `upsert_datafields(conn, rows)` — bulk `executemany` into `datafields` table
- `expr_exists(conn, expression)` — point-lookup via `idx_alphas_expr` index; returns `alpha_id` string or `None`

Schema is copied verbatim from `01-CONTEXT.md` Specific Artifacts (locked). No third-party dependencies — only `sqlite3`, `pathlib`, `typing`, `datetime`.

## Tasks

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | Create db.py with schema and CRUD functions | Done | a76ae35 |

## Verification Results

- Inline round-trip test: ALL ASSERTIONS PASSED
- `python -c "import db; print('import ok')"`: import ok
- `grep -c "alpha_kb.db" .gitignore`: 1
- `grep -c "^def " db.py`: 6
- Imports are stdlib-only: sqlite3, pathlib, typing, datetime

## Deviations from Plan

None - plan executed exactly as written.

The `.gitignore` already contained `alpha_kb.db` (line 7) from project initialization, so no modification was needed.

Note: Python 3.14 emits a `DeprecationWarning` for `datetime.utcnow()` (used in `upsert_checks`). The warning appears only in the verification test (which mirrors the plan's inline test verbatim). The function body is correct as written for this codebase's stdlib-only constraint.

## Known Stubs

None. All six functions are fully implemented and wired.

## Threat Flags

No new threat surface beyond what the plan's threat model covers. `alpha_kb.db` is gitignored (T-01-01 mitigated). WAL mode provides crash consistency (T-01-02 accepted). Path parameter is developer-controlled (T-01-03 accepted).

## Self-Check: PASSED

- db.py exists: FOUND
- commit a76ae35 exists: FOUND
- All assertions passed in verification run
- alpha_kb.db in .gitignore: confirmed (count=1)
- 6 top-level def statements confirmed
