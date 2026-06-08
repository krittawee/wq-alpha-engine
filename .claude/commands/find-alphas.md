# /find-alphas — Grounded Alpha Discovery Command

Orchestrates the Researcher → Ideator pipeline, emits a grounded Obsidian thesis
note to `alpha-kb/Theses/`, and writes one `runs` row per invocation.

**STOPS at candidates for human review. Does NOT grade/simulate (D-02 LOCKED).**

---

## What this command does

1. **[AGENT: Deterministic grounding]** Call `researcher.build_thesis(conn)` to get:
   - The deterministic archetype selection (rotation via `runs` table row count)
   - Grounded `source_operators` (⊆ `operators.name` from live catalog)
   - Grounded `source_datafields` (⊆ `datafields.id`, USA/TOP3000/delay=1)
   - `cited_insights` — 3 citable facts from populated `alphas`/`checks` columns
   - `cited_alpha_ids` — alpha IDs referenced in the insights

2. **[AGENT: Write LLM prose]** Using the grounded facts from step 1, author the
   hybrid prose sections (D-03):

   **Thesis prose (one paragraph):** Write a concise, specific claim:
   - Signal: what the expression measures (tied to `source_operators`/`source_datafields`)
   - Horizon: approximate holding period / lookback window
   - Edge: why this signal predicts returns on the WorldQuant BRAIN platform
   - Ground it in the `cited_insights` (e.g. the 59-alpha clean pool, the most common
     FAIL check, or the best UNSUBMITTED alpha by sharpe from the SQLite DB)

   **Economic rationale (2-4 sentences):** Explain the *mechanism*:
   - Who is on the wrong side of the trade and why?
   - Why does the edge persist (friction, behavioral, information asymmetry)?
   - Reference at least one fact from `cited_insights` to tie the prose to DB evidence

3. **[AGENT: Call find_alphas]** Invoke `find_alphas.find_alphas()` with the authored prose:

   ```python
   import find_alphas

   prose = {
       "thesis_prose": "<your authored thesis paragraph>",
       "rationale_prose": "<your authored economic rationale>",
   }

   result = find_alphas.find_alphas(prose=prose)
   ```

   This call:
   - Runs `researcher.build_thesis` → `ideator.generate_candidates` internally
   - Writes the thesis note to `alpha-kb/Theses/YYYY-MM-DD-<archetype>-<slug>.md`
   - Writes one row to the `runs` table (run_id, archetype, started_at, iterations, notes)
   - Returns `{run_id, note_path, archetype, candidate_count, queueable_count}`

4. **[AGENT: STOP and present to human]** Present the results for human review:
   - The note path and run_id
   - The queueable candidate count and archetype
   - The seeds.txt-format candidate list (lifted from the note or the ideator output)
   - **Explicit instructions: grading is run SEPARATELY — do NOT grade here**

---

## STOP BEFORE GRADING (D-02 LOCKED)

This command **MUST NOT** call `grade.*`, `simulate`, `client.simulate`, or any
BRAIN submission endpoint. Grading is the human's next step:

```bash
# Copy the seeds.txt block from the note to a file, then:
python cli.py <seeds-file> --workers 3
```

Or reference `alpha-kb/Theses/<note-path>` and lift the fenced block manually.

**Reason:** Single-shot biometric auth (Persona). Re-auth in-loop risks 429
BIOMETRICS_THROTTLED (15-30 min lockout). The human controls the auth timing.

---

## Module references

- `researcher.py` — `build_thesis(conn, archetype=None)` — deterministic grounding
- `ideator.py` — `generate_candidates(conn, thesis)`, `queueable(candidates)`,
  `to_seeds_text(candidates)` — candidate generation, validate gate, dedup
- `find_alphas.py` — `find_alphas(db_path, archetype, prose)` — full orchestrator;
  `render_note(thesis, candidates, run_id, prose)` — note template;
  `write_runs_row(conn, run_id, thesis, note_path, candidate_count)` — D-06 runs write
- `db.py` — `init_db(path)` — DB connection; `expr_exists(conn, expr)` — dedup

---

## Optional: Override archetype

```python
result = find_alphas.find_alphas(archetype="value_garp", prose=prose)
```

Valid archetypes: `reversal`, `momentum`, `value_garp`, `quality`, `growth`,
`low_volatility`, `liquidity_volume`, `sentiment_event`.

---

## Output

After `find_alphas.find_alphas()` completes:

1. **Note file:** `alpha-kb/Theses/YYYY-MM-DD-<archetype>-<run_id>.md`
   - Frontmatter: title, date, status: proposed, archetype, run_id, region, universe,
     delay, source_operators, source_datafields, cited_alpha_ids, cited_insights,
     candidate_count, tags
   - Body: Thesis (agent prose) → Economic rationale (agent prose) → Grounding tables
     → Past-result insight cited → Candidate expressions (seeds.txt block + dedup table)
     → Next steps checklist

2. **DB:** One `runs` row (run_id, thesis=archetype, started_at, iterations=candidate_count,
   num_pass=NULL, notes=note_path)

3. **Human output:** Present to the user:
   - `run_id` and `note_path`
   - Archetype and candidate summary
   - The seeds.txt block for grading reference
   - Reminder: grade separately via `python cli.py <seeds-file>`
