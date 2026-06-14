---
phase: 02-grounded-generation
plan: "03"
subsystem: find-alphas-orchestrator
tags: [find-alphas, vault-scaffold, obsidian, runs-table, orchestrator, d-02-compliant]
dependency_graph:
  requires: [researcher.py, ideator.py, db.py, alpha_kb.db]
  provides: [find_alphas.py, alpha-kb/, .claude/commands/find-alphas.md]
  affects: [02-04-checkpoint]
tech_stack:
  added: []
  patterns: [researcher-ideator-pipeline, obsidian-vault-emit, runs-row-write, hybrid-llm-prose]
key_files:
  created:
    - find_alphas.py
    - alpha-kb/Theses/.gitkeep
    - alpha-kb/Archetypes/.gitkeep
    - alpha-kb/Failures/.gitkeep
    - alpha-kb/README.md
    - .claude/commands/find-alphas.md
  modified:
    - .gitignore
decisions:
  - "Removed alpha-kb/ from .gitignore — vault must be git-tracked (D-05); it had been added pre-plan"
  - "Note filename includes run_id suffix (YYYY-MM-DD-<archetype>-<run_id>.md) for day+archetype uniqueness"
  - "Thesis note for test run committed as a real artifact (git-tracked as specified by D-05)"
metrics:
  duration: "~305s (~5 minutes)"
  completed: "2026-06-08"
  tasks_completed: 2
  files_changed: 7
---

# Phase 02 Plan 03: /find-alphas Command + Obsidian Vault + Runs Row — Summary

**One-liner:** Full Researcher->Ideator orchestrator emitting YAML-frontmattered Obsidian thesis notes to a git-tracked alpha-kb/ vault and writing one runs row per invocation, with a hybrid LLM-prose command file that hard-stops before grading (D-02).

## What Was Built

`find_alphas.py` (479 lines) exports 4 public functions:

- `slugify(text, max_len=40)` — converts text to a path-safe lowercase slug; strips non-alnum chars and collapses hyphens (T-02-09 path traversal mitigation).
- `render_note(thesis, candidates, run_id, prose=None)` — builds the full Obsidian Markdown thesis note: YAML frontmatter (title, date, status, archetype, run_id, region/universe/delay, source_operators, source_datafields, cited_alpha_ids, cited_insights, candidate_count, tags) + body sections in template order (Thesis → Economic rationale → Grounding tables → Past-result insight cited → Candidate expressions → Next steps). Optional `prose` dict injects LLM-authored text (D-03); if None, clearly-marked placeholders are inserted.
- `write_runs_row(conn, run_id, thesis, note_path, candidate_count)` — parameterized INSERT into `runs` table using only the confirmed db.py:37-40 schema columns (run_id, thesis=archetype, started_at=iso utc, iterations=candidate_count, num_pass=NULL, notes=note_path). T-02-11 mitigation.
- `find_alphas(db_path, archetype, prose)` — full orchestrator: opens conn via db.init_db; calls researcher.build_thesis; calls ideator.generate_candidates; generates run_id = uuid4()[:8]; computes note path; renders and writes the note; calls write_runs_row; closes conn; returns {run_id, note_path, archetype, candidate_count, queueable_count}. Prints human handoff instructions. DOES NOT call grade/simulate/login (D-02).

Vault scaffold created:
- `alpha-kb/Theses/` — thesis notes emitted here by find_alphas()
- `alpha-kb/Archetypes/` — scaffold for Phase 4
- `alpha-kb/Failures/` — scaffold for Phase 3+
- `alpha-kb/README.md` — documents layout, frontmatter keys, linking loop, grading handoff

`.claude/commands/find-alphas.md` — hybrid command (D-03): instructs the agent to (1) call researcher.build_thesis for deterministic grounding, (2) author Thesis + Economic-rationale prose grounded in the cited operators/fields/insights, (3) invoke find_alphas.find_alphas(..., prose=<agent prose>) to assemble and write the note and runs row, (4) STOP and present the candidate set + note path to the human. Explicitly states grading is run separately via `python cli.py <seeds-file>` (D-02).

## Verification Results

```
PASS: vault scaffold (alpha-kb/Theses/, Archetypes/, Failures/, README.md)
PASS: function definitions (render_note, write_runs_row, find_alphas, slugify)
PASS: render_note sections (all 6 body sections + all frontmatter keys present)
PASS: seeds block and dedup table (fenced block + | # | expression | archetype | dedupe | table)
PASS: D-02 grep gate (0 grade./simulate(/login( calls in find_alphas.py)
PASS: find_alphas() runs row + note written

Task 1 verify:
  OK note len 4338   # render_note output with all required sections

Task 2 verify:
  OK 366a0cfb alpha-kb/Theses/2026-06-08-reversal-366a0cfb.md   # first run (reversal)
  OK f6b0d306 alpha-kb/Theses/2026-06-08-momentum-f6b0d306.md   # second run (momentum rotation)

Archetype rotation working: runs table row count 1 → archetype index 1 (momentum)
D-02 grep gate: 0
find_alphas.py: 479 lines (> 90 minimum)
```

## Decisions Made

1. **Removed alpha-kb/ from .gitignore:** The vault was already in `.gitignore` when this plan executed. D-05 requires the vault to be git-tracked, so `alpha-kb/` was removed from `.gitignore` and all vault files were staged. This is the correct behavior per the design doc.

2. **Note filename includes run_id suffix:** The plan specified `YYYY-MM-DD-<archetype>-<slug>.md`. Since the archetype is the only natural "slug" available at this stage (the thesis prose comes from the LLM step, not from deterministic code), the run_id is appended to guarantee uniqueness when find_alphas() is called multiple times on the same day for the same archetype. Filename: `YYYY-MM-DD-<archetype>-<run_id>.md`.

3. **Parameterized INSERT for runs row (T-02-11):** `write_runs_row` uses a parameterized `conn.execute(... VALUES (?, ?, ?, ?, ?, ?))` to prevent injection; only the confirmed 6-column schema is written.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed alpha-kb/ from .gitignore**
- **Found during:** Task 1 — after creating vault directories, `git status` showed `alpha-kb/` as gitignored rather than untracked.
- **Issue:** `.gitignore` contained `alpha-kb/` which would prevent the git-tracked vault (D-05) from being committed.
- **Fix:** Removed `alpha-kb/` line from `.gitignore` and added `.gitignore` to the Task 1 commit.
- **Files modified:** `.gitignore`

**2. [Rule 1 - Bug] D-02 grep gate false positive from docstring**
- **Found during:** Task 1 acceptance check — `grep -v '^#' find_alphas.py | grep -c -E 'grade\.'` returned 1 instead of 0.
- **Issue:** The `write_runs_row` docstring contained the string `grade.py fills this later` — the pattern `grade\.` matched it even though it is not a function call.
- **Fix:** Changed docstring text to `the grader fills this later` — no code behavior change.
- **Files modified:** `find_alphas.py` (docstring only)

## Known Stubs

The `## Grounding: operators & fields cited` table in `render_note` outputs `—` for Category/Definition and Description/Dataset/Type columns (the thesis dict only carries field IDs and operator names, not their catalog metadata). These columns are intentional cosmetic stubs — the grounding assertion is that the tokens ARE in the catalog (guaranteed by researcher.build_thesis intersection), not that the note displays their full metadata. Phase 4 or a future polish pass could enrich these columns by doing a catalog JOIN at render time.

## Threat Flags

None. No new network endpoints, auth paths, or BRAIN API calls introduced.
- T-02-08 (D-02 auto-grade): mitigated — grep gate = 0, command file explicitly stops before grading.
- T-02-09 (path traversal): mitigated — slugify strips non-alnum/hyphen chars; archetype constrained to 8-label set.
- T-02-10 (NULL frontmatter): mitigated — cited_insights/cited_alpha_ids sourced from researcher.gather_insights (populated columns only).
- T-02-11 (wrong runs columns): mitigated — parameterized INSERT on the confirmed 6-column schema.

## Self-Check: PASSED

- find_alphas.py exists: FOUND (479 lines)
- alpha-kb/Theses/.gitkeep exists: FOUND
- alpha-kb/Archetypes/.gitkeep exists: FOUND
- alpha-kb/Failures/.gitkeep exists: FOUND
- alpha-kb/README.md exists: FOUND
- .claude/commands/find-alphas.md exists: FOUND
- Commits:
  - 3a70293 (feat Task 1: vault scaffold + render_note + write_runs_row)
  - 93ecff0 (feat Task 2: find_alphas orchestrator + command file)
- D-02 grep gate: 0
- All must_have artifacts satisfied (render_note, write_runs_row, find_alphas, vault dirs, command file)
- Thesis note generated by verification: alpha-kb/Theses/2026-06-08-reversal-366a0cfb.md
