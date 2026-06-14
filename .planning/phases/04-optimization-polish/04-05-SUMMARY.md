---
phase: 04-optimization-polish
plan: "05"
subsystem: obsidian-prose-layer
tags: [obsidian, notes, wikilinks, archetype, failure-family, decay, note-path, two-way-link]

# Dependency graph
requires:
  - phase: 04-01
    provides: alphas.note_path column migration in init_db (prerequisite for two-way link)
  - phase: 04-01
    provides: db.py with checks table (SELECT name FROM checks WHERE alpha_id=? AND result='FAIL')
  - phase: phase-01-03
    provides: researcher.ARCHETYPES (8 archetype labels used as iteration source)
  - phase: phase-01-03
    provides: find_alphas.slugify (path-traversal-safe filename generation)
provides:
  - obsidian.regen_archetype_notes (OPT-03: one note per archetype, two-way note_path update)
  - obsidian.regen_failure_notes (OPT-03: one note per failure family, two-way note_path update)
  - obsidian.write_decay_note (OPT-02 integration: Decay.md overwrite with degraded-alpha table)
  - obsidian.regen_all (callable by optimizer.run_optimize as side-effect)
affects:
  - 04-03 (optimizer.py calls obsidian.regen_all(conn) as side-effect of /optimize)
  - 04-04 (decay_monitor.py calls obsidian.write_decay_note(degraded, conn))

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deterministic note regen from DB: write to stable filename each run — no stale drift (D-10)"
    - "Two-way linking: note embeds [[alpha_id]] wikilinks; alphas.note_path updated via UPDATE ... WHERE archetype=?"
    - "Failure family grouping: PRIORITY order pick (CONCENTRATED_WEIGHT > HIGH_TURNOVER > ... > LOW_SHARPE) — same family = same .md"
    - "Path-safe filenames: all slugify(archetype) and slugify(family) calls strip /, .., null bytes"
    - "Single overwrite Decay.md: full history in checks_history; note is current-snapshot view (D-10 philosophy)"

key-files:
  created:
    - obsidian.py
  modified: []

key-decisions:
  - "regen_all does NOT call write_decay_note — decay note is written by decay_monitor per D-11"
  - "Failure family grouping by primary check name (not archetype+check) — per RESEARCH.md Pattern 5 discretion recommendation"
  - "alphas.note_path UPDATE uses archetype= for archetype notes and alpha_id IN (...) for failure notes — different granularity"
  - "vault_root defaulted to VAULT_ROOT constant but always overridable — tests use tmp_path"
  - "wikilinks intentionally unresolved in Obsidian (no individual alpha notes yet) — documented in each note footer per Pitfall 5"

patterns-established:
  - "Obsidian note module: _render_*_note helpers return str; public regen_ functions write and update DB"
  - "Note write pattern: note_path.write_text(content, encoding='utf-8') + conn.execute UPDATE note_path"

requirements-completed: [OPT-03]

# Metrics
duration: 15min
completed: 2026-06-11
---

# Phase 04 Plan 05: Obsidian Prose Layer (obsidian.py) Summary

**Deterministic Obsidian note generation from SQLite DB — archetype notes, failure-family notes, decay summary — with [[alpha_id]] wikilinks and two-way alphas.note_path DB->note linking**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-06-11
- **Completed:** 2026-06-11
- **Tasks:** 2 (combined into single file commit)
- **Files created:** 1 (obsidian.py)

## Accomplishments

- `obsidian.py` created with 4 public functions: `regen_archetype_notes`, `regen_failure_notes`, `write_decay_note`, `regen_all`
- `regen_archetype_notes(conn, vault_root)`: iterates `researcher.ARCHETYPES` (8 entries), renders frontmatter+3 sections (Heuristics/NEAR/PASS tables with `[[alpha_id]]` wikilinks), writes `vault_root/Archetypes/{slugify(archetype)}.md`, then `UPDATE alphas SET note_path=? WHERE archetype=?`
- `regen_failure_notes(conn, vault_root)`: queries `DISTINCT alpha_id FROM alphas WHERE status='fail'`, groups by `get_failure_family()` PRIORITY order, writes one `vault_root/Failures/{slugify(family)}.md` per family, updates `note_path` for all family members
- `write_decay_note(degraded_list, conn, vault_root)`: overwrites `vault_root/Decay.md` with current degraded-alpha markdown table; returns str path
- `regen_all(conn, vault_root)`: calls both regen functions, returns `{"archetype_notes": [...], "failure_notes": [...]}` — intentionally excludes `write_decay_note` per D-11
- All filenames through `find_alphas.slugify()` — path-traversal safe (T-04-17 mitigated)
- All SQL in parameterized `?` form (T-04-18 mitigated)

## Task Commits

1. **Tasks 1+2: obsidian.py complete module** - `7166aeb` (feat)

## OPT-03 Tests

All 4 OPT-03 tests in test_phase4.py pass:

| Test | Status |
|------|--------|
| test_archetype_notes_count | PASSED |
| test_failure_notes_families | PASSED |
| test_note_path_written | PASSED |
| test_wikilinks_in_notes | PASSED |

## Files Created/Modified

- `obsidian.py` (created, 499 lines) — complete OPT-03 service module

## Decisions Made

- `regen_all` does NOT call `write_decay_note` — the decay note is written by `decay_monitor.run_decay`, not `/optimize` (per D-11 locked decision)
- Failure family grouping uses primary check name (not archetype+check combo) per RESEARCH.md Pattern 5 discretion — avoids sparse families with 60 FAIL alphas in DB
- Note footer added to all note types per Pitfall 5 (wikilinks intentionally unresolved)
- `vault_root` parameter defaults to `VAULT_ROOT` constant but all callers (tests, optimizer, decay_monitor) pass explicit path for isolation

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all functions fully implemented. Note: archetype notes will have empty Heuristics/PASS sections for archetypes with no PASS/ACTIVE alphas in DB yet (expected behavior per Pattern 6 in RESEARCH.md, not a stub).

## Threat Surface Scan

No new network endpoints, auth paths, or trust boundaries introduced. File writes confined to `alpha-kb/` vault directory. T-04-17 and T-04-18 mitigated as designed.

## Self-Check

Files exist:
- obsidian.py: FOUND (created in worktree)

Commits:
- 7166aeb: FOUND

## Self-Check: PASSED

---
*Phase: 04-optimization-polish*
*Completed: 2026-06-11*
