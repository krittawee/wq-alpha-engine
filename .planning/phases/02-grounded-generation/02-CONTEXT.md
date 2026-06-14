# Phase 2: Grounded Generation - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning
**Source:** Grounding brief (02-GROUNDING.md) + human decisions resolved via AskUserQuestion

<domain>
## Phase Boundary

Phase 2 builds two new flat Python modules in `/Users/winter.__.kor/quant/` plus one Claude Code command:
- `researcher.py` — produces a grounded thesis note (hybrid: deterministic archetype selection + LLM thesis prose)
- `ideator.py` — turns a thesis into 4–8 FastExpr candidates using only verified operators/fields, deduped against the DB
- `/find-alphas` — Claude Code command orchestrating Researcher → Ideator, emitting an Obsidian thesis note

**In scope:** thesis generation, grounded candidate generation, validator pre-filter, dedup, archetype tagging, Obsidian vault scaffold + note emit, `runs` table writes.

**Out of scope (do NOT build):** auto-grading/simulation inside `/find-alphas` (human runs grading separately), the diagnose+mutate Editor loop (Phase 3), self-corr/structural-similarity pre-filtering (Phase 3), Settings Optimizer / decay monitor (Phase 4).

**Requirements:** GEN-01, GEN-02
</domain>

<decisions>
## Implementation Decisions (LOCKED — human-resolved 2026-06-08)

### Candidate volume
- Ideator emits **4–8 FastExpr candidates per thesis** (sized to ≤3-concurrent / ~2-min-per-sim / single-shot-auth constraints).

### Grading handoff
- `/find-alphas` **STOPS for human review** — it emits thesis + dedup'd candidates only. It MUST NOT call `grade.*` / simulate. Grading is run separately by the human via `python cli.py <seeds-file>` (Path A). The 02-04 checkpoint may run a manual smoke test, but the command itself stops at candidates.

### Researcher architecture
- **Hybrid**: deterministic code selects the archetype (rotate under-explored archetypes / target the 59-alpha clean pool) and pulls grounded catalog + past-result facts; an LLM agent writes the thesis prose / economic rationale.

### Archetype tagging
- **Inherited from thesis**: Researcher sets one `archetype` in thesis frontmatter; all candidates from that thesis inherit it (one thesis = one archetype). Flows into `upsert_alpha.archetype` at grade time. No per-candidate or classifier logic in Phase 2.

### Obsidian vault
- Vault at **`/Users/winter.__.kor/quant/alpha-kb/`, git-tracked** (per design doc `docs/plans/2026-06-07-alpha-system-design.md`). Scaffold `Theses/`, `Archetypes/`, `Failures/`. Theses emit to `alpha-kb/Theses/YYYY-MM-DD-<archetype>-<slug>.md`.

### runs table
- **Phase 2 owns it.** Begin populating the currently-empty `runs` table (run_id, thesis note path, notes) — one row per `/find-alphas` invocation.

### Self-corr pre-filter
- **None in Phase 2.** Rely entirely on `grade.py`'s post-sim `POST /alphas/{id}/check`. Structural-similarity / FSA pre-filtering deferred to Phase 3.

### Claude's Discretion
- Exact thesis-slug derivation, internal module structure, how deterministic archetype rotation reads "under-explored" from the DB, prompt wording for the LLM thesis step.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Primary grounding
- `.planning/phases/02-grounded-generation/02-GROUNDING.md` — live-verified catalog inventory, exact Phase 1 integration contract, citable past-alpha insights, 8-archetype taxonomy, Obsidian thesis-note template, lessons from reference tooling, proposed 4-plan breakdown.

### Phase 1 code to integrate with (exact signatures in the brief)
- `db.py` — `init_db()` (db.py:55), `expr_exists(conn, expr)` dedup helper (db.py:149), `upsert_alpha(conn, dict)` (db.py:69, `archetype` is a writable column)
- `validate.py` — `validate(conn, expr) -> (bool, reason)` gate (validate.py:23)
- `grade.py` / `cli.py` — grading handoff (Path A: seeds file → `python cli.py <file>`); NOT invoked by Phase 2's `/find-alphas`
- `wq_login.py` — `login()` single-shot auth (never re-auth in-loop)

### Project constraints
- `CLAUDE.md` — single-shot auth, ≤3 concurrent sims, never hardcode check limits (read from BRAIN `is.checks`)
- `docs/plans/2026-06-07-alpha-system-design.md` — vault location prescription
</canonical_refs>

<success_criteria>
## Success Criteria (from ROADMAP.md)

1. `/find-alphas` produces a thesis note in Obsidian that cites specific operators/fields from the synced catalog and ≥1 insight from past alpha results in SQLite.
2. Ideator outputs expressions where every operator and data-field token is confirmed present in the `operators`/`datafields` tables — the local validator rejects ZERO Ideator outputs for unknown tokens.
3. Each generated expression is tagged with an archetype and confirmed absent from `alphas.expression` (via `db.expr_exists`) before being queued for grading.
</success_criteria>

<deferred>
## Deferred Ideas
- Editor diagnose+mutate loop, memory-aware FSA, local PnL pre-filter → Phase 3.
- Settings Optimizer, decay monitor, Obsidian prose/Archetypes layer → Phase 4.
</deferred>

---

*Phase: 02-grounded-generation*
*Context resolved 2026-06-08*
