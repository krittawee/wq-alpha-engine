# /bruteforce — AI-Free Brute-Force Alpha Discovery (Tool B)

Enumerate parameterized templates, validate locally, probe-sim a sample, bulk-sim survivors
at ≤3 concurrent on the cached BRAIN session, gate through additivity. Fully standalone —
no LLM dependency. Runs when Claude Code AI quota is exhausted.

**Auth: wq_login is called ONCE before the loop. A 401 mid-loop stops the run cleanly —
never re-auth in-loop (CLAUDE.md lockout constraint).**

---

## What this command does

1. **[AGENT: Single-shot auth]** Call `wq_login.login()` exactly ONCE before running the
   engine. Store the returned `client`. Do NOT call it again anywhere inside the run.

   Reason: Repeated biometric re-auth triggers 429 BIOMETRICS_THROTTLED (15–30 min lockout).
   A single authenticated session is valid for the full brute-force run.

2. **[AGENT: Run bruteforce.bruteforce()]** Import and call `bruteforce()` with all args:

   ```python
   import bruteforce
   from wq_login import login

   client = login()  # ONCE — never inside the loop

   result = bruteforce.bruteforce(
       client=client,
       db_path="alpha_kb.db",    # override with --db if needed
       delay=0,                   # override with --delay (default 0 for Tool B)
       quota=5,                   # override with --quota
       probe_size=5,              # override with --probe-size
       template_names=None,       # override with --templates (space-separated names)
   )
   ```

   The `bruteforce()` function internally runs this pipeline for each template:
   - `selfcorr.backfill_active_pnl` — one-time PnL cache fill before the loop (sequential)
   - `probe_delay.probe_and_gate` — one-shot delay probe (fires when delay != 1, before loop)
   - For each template in TEMPLATES (or subset from --templates):
     - `templates.expand_slots` — Cartesian product over slot values → combo list
     - `validate.validate` — local token/operator check per combo (drops unknowns)
     - `templates.probe_spread_sample` — spread sample (≤probe_size, covers all slot values)
     - `grade.grade_many(max_workers=3)` — probe sample sims (≤3 concurrent)
     - `editor.classify_from_checks` — probe verdict: abandon if all probes are far-fail
     - `bruteforce._bulk_sim_quota_aware` — bulk-sim survivors (≤3 concurrent, stops at quota)
     - `additivity.rank_by_proxy` + `additivity.confirm_additive` — additivity gate
     - `db.insert_bruteforce_run` / `db.update_bruteforce_run` — per-template persistence

3. **[AGENT: Handle 401]** If a `requests.exceptions.HTTPError` with status 401 is raised,
   print a clear message and stop. Do NOT attempt to re-authenticate:

   ```python
   import requests, sys
   try:
       result = bruteforce.bruteforce(...)
   except requests.exceptions.HTTPError as e:
       if getattr(getattr(e, "response", None), "status_code", None) == 401:
           print("[bruteforce] AUTH EXPIRED — 401 received. Re-run /bruteforce to re-authenticate.")
           sys.exit(1)
       raise
   ```

   The engine also handles 401 internally (exits with `sys.exit(1)` and marks the partial
   `bruteforce_runs` row). This outer catch is a safety net for 401s raised before the loop.

4. **[AGENT: Display results]** Present the result dict to the user:
   - `quota_count` — number of confirmed-additive survivors found this run
   - `n_templates_done` — templates fully processed (probe-abandoned templates count)
   - `stop_reason` — `"quota_met"` | `"401"` | `"dry"`
   - `additive_ids` — list of alpha_ids that passed IS checks + additivity gate (ready for review)

---

## Stop conditions (D-09)

The template loop stops when ANY of these conditions are met:

1. **quota_met** — `quota_count >= --quota` (enough additive survivors found; default 5)
2. **401** — session expiry detected mid-loop; partial progress is persisted; run exits cleanly
3. **dry** — all requested templates processed; quota not met

**Note:** IS-pass-but-correlated alphas do NOT count toward quota (D-07). Only alphas that
pass both IS checks AND the additivity gate increment `quota_count`.

---

## Flags (CLI usage)

```bash
python bruteforce.py [--db alpha_kb.db] [--delay 0] [--quota 5] [--probe-size 5] [--templates ...]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `alpha_kb.db` | SQLite knowledge-base path |
| `--delay` | `0` | Simulation delay. `0` = delay-0 (default; decorrelated from delay-1 book). Use `--delay 1` to override. |
| `--quota` | `5` | Stop after this many additive survivors (IS-pass + additivity-gate pass). |
| `--probe-size` | `5` | Probe sample size per template (spread-covers all distinct slot values). |
| `--templates` | *(all)* | Space-separated template names to run. Omit to run all 4 shapes. |

---

## Auth constraint (CLAUDE.md — non-negotiable)

`wq_login.login()` is called **exactly once** before `bruteforce()`. Inside `bruteforce()`
there is no auth call. This is intentional:

- Repeated biometric auth → 429 BIOMETRICS_THROTTLED (15–30 min lockout)
- A 401 inside the loop means the session expired → stop cleanly, never retry
- The user controls when to re-authenticate by re-running the command

---

## Concurrency constraint (CLAUDE.md — non-negotiable)

`bruteforce._bulk_sim_quota_aware()` uses `ThreadPoolExecutor(max_workers=3)`. This
enforces BRAIN's concurrent simulation slot cap. Never raise this value.

The same ≤3 limit applies to the probe `grade.grade_many` call inside each template.

---

## Module references

- `bruteforce.py` — `bruteforce(client, db_path, delay, quota, probe_size, template_names)` — main engine
- `bruteforce.py` — `settings_grid_for_archetype(archetype)` — per-archetype settings combos
- `templates.py` — `TEMPLATES` (4 shapes), `expand_slots(conn, template)`, `probe_spread_sample(combos, slot_names, size)`
- `wq_login.py` — `login()` — single-shot biometric auth
- `validate.py` — `validate(conn, expression)` — local token/operator validation
- `grade.py` — `grade_one(client, conn, expr, run_id, settings, delay)`, `grade_many(...)`
- `editor.py` — `classify_from_checks(alpha_id, conn)` — probe verdict classification
- `additivity.py` — `rank_by_proxy(candidates, conn)`, `confirm_additive(client, alpha_id, conn)`
- `selfcorr.py` — `backfill_active_pnl(client, conn, db_path)` — pre-loop PnL cache fill
- `probe_delay.py` — `probe_and_gate(client, conn, requested_delay)` — delay-0 viability probe
- `db.py` — `init_db(path)`, `insert_bruteforce_run(conn, row)`, `update_bruteforce_run(conn, rowid, updates)`

---

## Output

After `bruteforce.bruteforce()` completes:

1. **quota_count** — additive survivors found this run (these alpha_ids are in `alphas` + `checks` tables)
2. **additive_ids** — alpha_ids that passed both IS checks and the additivity gate (ready for manual review and submission decision)
3. **DB** — per-template aggregates written to `bruteforce_runs` table; run metadata in `runs` table
4. **Failure summary** — per-template: `validate_dropped`, `probe_abandoned`, `IS_fail_*`, `gate_fail_correlated` counts (in `bruteforce_runs.failure_counts` JSON column)
