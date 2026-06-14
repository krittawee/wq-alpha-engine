# /optimize — Settings Optimizer + Obsidian Note Regen

Runs the Settings Optimizer over every NEAR alpha — proposing ≤4 settings variants per
alpha drawn from archetype heuristics blended with past PASS settings (never a blind grid
sweep), simulating them, and recording outcomes back to the DB — then regenerates the
Obsidian Archetype/Failure notes as a side-effect.

**Auth: wq_login is called ONCE before the optimizer loop. A 401 mid-run stops the run
cleanly — never re-auth in-loop (CLAUDE.md lockout constraint).**

---

## What this command does

1. **[AGENT: Single-shot auth]** Call `wq_login.login()` exactly ONCE before starting
   the optimizer. Store the returned `client`. Do NOT call it again anywhere inside the run.

2. **[AGENT: Run optimizer.run_optimize()]** Invoke the orchestrator:

   ```python
   import optimizer
   from wq_login import login

   client = login()  # ONCE — never inside the loop

   result = optimizer.run_optimize(
       client=client,
       db_path="alpha_kb.db",   # override with --db if needed
       max_workers=1,            # sequential — each variant needs different settings
   )
   ```

   `run_optimize()` internally:
   - Queries all NEAR alphas from the `alphas` table
   - For each, calls `build_variants()` to produce ≤4 settings variants per the
     `ARCHETYPE_HEURISTICS` table blended with past PASS settings in SQLite
   - Simulates each variant via `grade.grade_many` (sequential, single-shot auth)
   - Records outcomes back to the DB with `parent_alpha_id` lineage
   - Calls `obsidian.regen_all()` as a side-effect to refresh Archetype/Failure notes

3. **[AGENT: Handle 401]** If a `requests.exceptions.HTTPError` with status 401 is raised,
   print a clear message and stop. Do NOT attempt to re-authenticate:

   ```python
   import requests, sys
   try:
       result = optimizer.run_optimize(...)
   except requests.exceptions.HTTPError as e:
       if getattr(getattr(e, "response", None), "status_code", None) == 401:
           print("[optimize] AUTH EXPIRED — 401 received. Re-run /optimize to re-authenticate.")
           sys.exit(1)
       raise
   ```

4. **[AGENT: Display results]** Present the result dict to the user:
   - `near_alphas_processed` — number of NEAR alphas the optimizer ran over
   - `variants_simulated` — total settings variants simulated this run
   - `variants_passed` — variants that crossed into submittable (PASS) territory

---

## Flags (CLI usage)

```bash
python optimize.py [--db alpha_kb.db] [--max-workers 1]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `alpha_kb.db` | Path to alpha knowledge-base SQLite file |
| `--max-workers` | `1` | Concurrency for variant simulation (sequential by default) |

---

## Auth constraint (CLAUDE.md — non-negotiable)

`wq_login` is called **exactly once** before `run_optimize()`. Inside the optimizer there
is no auth call. This is intentional:

- Repeated biometric auth → 429 BIOMETRICS_THROTTLED (15–30 min lockout)
- A 401 inside the run means the session expired → stop cleanly, never retry
- The user controls when to re-authenticate by re-running the command

---

## Concurrency constraint (CLAUDE.md — non-negotiable)

`grade.grade_many` is called with `max_workers=1` for variant simulation — each variant
carries different settings and is simulated sequentially. The BRAIN concurrent-slot cap
(≤3) is never exceeded.

---

## Module references

- `optimizer.py` — `run_optimize(client, db_path, max_workers)`, `build_variants(alpha_row, conn)`, `ARCHETYPE_HEURISTICS`
- `wq_login.py` — `login()` — single-shot biometric auth
- `grade.py` — `grade_many(client, conn, expressions, run_id, settings_map=..., max_workers=1, db_path=db_path)`
- `selfcorr.py` — self-correlation gating reused from grading
- `obsidian.py` — `regen_all(conn, vault_root)` — Archetype/Failure note regen (run side-effect)
