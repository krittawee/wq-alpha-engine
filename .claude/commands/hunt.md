# /hunt — Autonomous Alpha Discovery Command

Runs the full research → generate(FSA) → grade(selfcorr) → editor → bounded loop
autonomously, returning the best new submittable alpha at the end of the budget.

**Auth: wq_login is called ONCE before the loop. A 401 mid-loop stops the run cleanly —
never re-auth in-loop (CLAUDE.md lockout constraint).**

---

## What this command does

1. **[AGENT: Single-shot auth]** Call `wq_login.login()` exactly ONCE before starting
   the loop. Store the returned `client`. Do NOT call it again anywhere inside the run.

2. **[AGENT: Run hunt.hunt()]** Invoke the orchestrator:

   ```python
   import hunt
   from wq_login import login

   client = login()  # ONCE — never inside the loop

   result = hunt.hunt(
       client=client,
       db_path="alpha_kb.db",    # override with --db if needed
       max_depth=2,               # override with --max-depth
       max_sims=30,               # override with --max-sims
       delay=1,                   # override with --delay (use 0 for delay-0 alphas)
   )
   ```

   The hunt() function internally chains:
   - `selfcorr.backfill_active_pnl` — one-time PnL cache fill (pre-loop, sequential)
   - `fsa.mine_frequent_motifs` — avoid-list for structural steering
   - `researcher.build_thesis` + `ideator.generate_candidates` — Gen 0 candidate pool
   - `fsa.filter_candidates` + `ideator.queueable` — FSA + validate gate
   - `grade.grade_many(max_workers=3, db_path=db_path)` — parallel grading (≤3 concurrent)
   - Loop: `editor.classify_from_checks` → `editor.diagnose_and_mutate` → `grade.grade_many`

3. **[AGENT: Handle 401]** If a `requests.exceptions.HTTPError` with status 401 is raised,
   print a clear message and stop. Do NOT attempt to re-authenticate:

   ```python
   import requests, sys
   try:
       result = hunt.hunt(...)
   except requests.exceptions.HTTPError as e:
       if getattr(getattr(e, "response", None), "status_code", None) == 401:
           print("[hunt] AUTH EXPIRED — 401 received. Re-run /hunt to re-authenticate.")
           sys.exit(1)
       raise
   ```

4. **[AGENT: Display results]** Present the result dict to the user:
   - `best_submittable`: alpha_id with highest Sharpe among all PASS alphas found, or None
   - `best_near`: list of NEAR alpha_ids for manual review or /iterate
   - `sims_used` / `max_sims`: budget consumed
   - `generations`: number of editor→grade loops completed
   - `diversity_before` / `diversity_after`: structural diversity metric snapshots

---

## Stop conditions (D-16)

The loop stops when ANY of these conditions are met:
1. **depth** — `max_depth` generations of editor→grade completed
2. **budget** — `sims_used >= max_sims` (hard ceiling, D-17)
3. **dry** — no NEAR alphas after a generation (nothing to feed the next round)

The loop does NOT stop on finding the first submittable alpha (D-16 locked).
The full budget is consumed regardless to maximise diversity exploration.

---

## Flags (CLI usage)

```bash
python hunt.py [--db alpha_kb.db] [--max-depth 2] [--max-sims 30] [--delay 1]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `alpha_kb.db` | Path to alpha knowledge-base SQLite file |
| `--max-depth` | `2` | Max editor→grade generations after Gen 0 |
| `--max-sims` | `30` | Hard simulation ceiling across all generations |
| `--delay` | `1` | Simulation delay. Use `--delay 0` for delay-0 alphas (explicit opt-in; default is delay-1). Fires a one-shot probe before the hunt loop when delay != 1 and max-sims > 0. |

Note: delay-0 requires `--delay 0`; omitting `--delay` defaults to delay-1. A probe sim fires first to confirm BRAIN supports delay-0 on this session (fails fast if coerced). No probe fires when `--max-sims 0` is used (dry run).

---

## Auth constraint (CLAUDE.md — non-negotiable)

`wq_login` is called **exactly once** before `hunt()`. Inside `hunt()` there is no auth
call. This is intentional:

- Repeated biometric auth → 429 BIOMETRICS_THROTTLED (15–30 min lockout)
- A 401 inside the loop means the session expired → stop cleanly, never retry
- The user controls when to re-authenticate by re-running the command

---

## Concurrency constraint (CLAUDE.md — non-negotiable)

`grade.grade_many` is always called with `max_workers=3`. This enforces BRAIN's
concurrent simulation slot cap. Never raise this value.

---

## Module references

- `hunt.py` — `hunt(client, db_path, max_depth, max_sims, delay=1)` — full orchestrator
- `wq_login.py` — `login()` — single-shot biometric auth
- `grade.py` — `grade_many(client, conn, expressions, run_id, max_workers=3, db_path=db_path)`
- `editor.py` — `classify_from_checks(alpha_id, conn)`, `diagnose_and_mutate(alpha_id, conn, avoid_motifs=...)`
- `fsa.py` — `mine_frequent_motifs(conn)`, `filter_candidates(candidates, avoid_motifs)`, `diversity_metric(conn)`
- `researcher.py` — `build_thesis(conn, avoid_motifs=...)`
- `ideator.py` — `generate_candidates(conn, thesis)`, `queueable(candidates)`
- `selfcorr.py` — `backfill_active_pnl(client, conn, db_path)` — pre-loop, sequential only

---

## Output

After `hunt.hunt()` completes:

1. **best_submittable** — alpha_id of the best PASS alpha by Sharpe (None if no PASS found)
2. **best_near** — list of NEAR alpha_ids (feed to `/iterate` for targeted mutation)
3. **DB** — all graded alphas written to `alphas` + `checks` tables with full lineage
4. **diversity snapshot** — before/after `fsa.diversity_metric` comparison for criterion 4
