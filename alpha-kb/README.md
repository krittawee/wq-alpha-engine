# alpha-kb — Grounded Alpha Knowledge Base

Git-tracked Obsidian vault for the Grounded Alpha Discovery System
(`~/quant`). Created by Phase 2 (02-03-PLAN.md).

## Vault Layout

```
alpha-kb/
  Theses/        <- Phase 2: /find-alphas emits one note per run
  Archetypes/    <- Phase 4: archetype overview pages (scaffold only)
  Failures/      <- Phase 3+: post-grade failure analysis notes (scaffold only)
```

## Theses note naming

`Theses/YYYY-MM-DD-<archetype>-<slug>.md`

- `YYYY-MM-DD` — UTC date the note was created (from `find_alphas.find_alphas()`)
- `<archetype>` — one of the 8 taxonomy labels: `reversal`, `momentum`, `value_garp`,
  `quality`, `growth`, `low_volatility`, `liquidity_volume`, `sentiment_event`
- `<slug>` — slugified snippet from the thesis claim (max 40 chars)

## Frontmatter keys

| Key | Description |
|-----|-------------|
| `title` | Human-readable thesis title |
| `date` | ISO date (YYYY-MM-DD) |
| `status` | `proposed` → `grading` → `graded` → `shelved` |
| `archetype` | One of the 8 taxonomy labels |
| `run_id` | UUID-8 — FK to `runs.run_id` and `alphas.run_id` |
| `region` | `USA` |
| `universe` | `TOP3000` |
| `delay` | `1` |
| `source_operators` | Subset of `operators.name` (catalog-verified) |
| `source_datafields` | Subset of `datafields.id` (synced slice) |
| `cited_alpha_ids` | FK → `alphas.alpha_id` (provenance) |
| `cited_insights` | Human-readable insight strings from SQLite |
| `candidate_count` | Number of candidates embedded in note |
| `tags` | `[thesis, alpha, <archetype>]` |

## Linking loop

- `runs.notes` stores the relative path to the emitted thesis note (FK from code → note).
- `alphas.run_id` traces each graded alpha back to its thesis note.
- `cited_alpha_ids` in the frontmatter traces the thesis back to the SQLite rows that
  informed it (re-runnable provenance queries).

## Grading handoff

The `/find-alphas` command STOPS at candidates. To grade:

```bash
python cli.py alpha-kb/Theses/<note-date>-<archetype>-<slug>-seeds.txt --workers 3
```

Or lift the seeds.txt-format fenced block from the note manually.

## References

- Design doc: `docs/plans/2026-06-07-alpha-system-design.md` (lines 259-268)
- Phase 2 context: `.planning/phases/02-grounded-generation/02-CONTEXT.md`
- Orchestrator: `find_alphas.py` (`find_alphas()`, `render_note()`, `write_runs_row()`)
