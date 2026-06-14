---
phase: 01-mvp-grading-engine
plan: "03"
subsystem: validation
tags: [sqlite3, regex, fastexpr, local-validator, stdlib]

# Dependency graph
requires:
  - phase: 01-01
    provides: "db.py with operators and datafields tables in SQLite"
provides:
  - "validate.py: single public validate(conn, expr) -> tuple[bool, str] function"
  - "validate_test.py: 10 in-memory test cases covering all behavior block assertions"
affects:
  - 01-04
  - grade.py

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Parameterized SQL queries only — never string-interpolated (T-03-01)"
    - "Fail-fast validation: empty -> parens -> operators -> datafields"
    - "re.findall(r'([A-Za-z_][A-Za-z0-9_]*)\s*\(') for operator token extraction"
    - "Self-contained test files with in-memory SQLite seeds (no pytest)"

key-files:
  created:
    - validate.py
    - validate_test.py
  modified: []

key-decisions:
  - "Pragmatic regex tokenizer rather than full FastExpr AST parser — sufficient for catching unknown tokens before wasting a 2-min simulation slot"
  - "Exclusion set for Python keywords prevents false 'unknown data field' errors for tokens like 'and', 'or', 'not'"
  - "Unbalanced parentheses rejected before any DB query — avoids unnecessary catalog round-trips for clearly malformed input"
  - "Empty operators table produces correct behaviour (rejects all operator tokens) — catalog sync must run first"

patterns-established:
  - "validate() takes conn as first argument — caller (grade.py) owns the connection lifecycle"
  - "No import of wq_login, brain_client, or requests in validate.py — purely local"
  - "Test files are self-contained scripts: create in-memory conn, seed, assert, print PASSED"

requirements-completed:
  - ENG-03

# Metrics
duration: 8min
completed: 2026-06-07
---

# Phase 01 Plan 03: Local Expression Validator Summary

**stdlib-only validate.py with regex-based FastExpr tokenizer, parameterized SQL catalog checks, and fail-fast validation order (empty → parens → operators → datafields)**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-07T01:54:00Z
- **Completed:** 2026-06-07T02:02:21Z
- **Tasks:** 1 of 1
- **Files modified:** 2 created

## Accomplishments

- Created validate.py with exactly one public function `validate(conn, expression) -> tuple[bool, str]`
- All SQL queries use parameterized statements — T-03-01 (SQL injection) fully mitigated
- Validated 10 distinct behavior cases including: empty, whitespace, unbalanced parens, unknown operator, bare field, unknown field, nested multi-operator, numeric literals, keyword exclusions
- Zero new dependencies: only Python stdlib (sqlite3, re, typing)

## Task Commits

1. **Task 1: Implement validate.py with local expression validator** - `025eea7` (feat)

**Plan metadata:** (committed with SUMMARY below)

## Files Created/Modified

- `validate.py` - Local expression validator; single public validate() function; stdlib only
- `validate_test.py` - Self-contained test script with in-memory SQLite; 10 assertions; no pytest

## Decisions Made

- Used pragmatic regex tokenizer (not full FastExpr AST) — plan explicitly allows this and it catches the critical case of unknown tokens before a 2-minute BRAIN simulation slot is spent
- Exclusion set covers Python keywords that could appear in expressions (and, or, not, if, etc.) to prevent false "unknown data field" rejections
- Test file designed to run standalone with `python validate_test.py` — no pytest, no new deps

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None — validate.py has no hardcoded placeholder values or empty returns outside the empty-expression fast-path.

## Threat Flags

No new security surface beyond what the plan's threat model covers. T-03-01 (SQL injection via expression) is fully mitigated via parameterized queries throughout.

## Issues Encountered

None.

## Next Phase Readiness

- `validate.py` is ready for `import validate` in `grade.py` (Plan 01-04)
- The `validate.validate(conn, expression)` call pattern matches the `key_links` spec in 01-03-PLAN.md
- If the operators table is empty (catalog not yet synced), all operator tokens fail — this is correct and expected behaviour; grade.py should call sync first

---
*Phase: 01-mvp-grading-engine*
*Completed: 2026-06-07*
