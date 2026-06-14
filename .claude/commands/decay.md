# /decay — Decay Monitor

Re-checks every live (PASS / ACTIVE) alpha, appends the fresh check results to the
time-stamped `checks_history` table, and surfaces any alpha whose key metrics have
degraded beyond the threshold across successive check runs. Writes a `Decay.md` Obsidian note.

**Auth: wq_login is called ONCE before the monitor runs. A 401 mid-run stops the run
cleanly — never re-auth in-loop (CLAUDE.md lockout constraint).**

---

## What this command does

1. **[AGENT: Single-shot auth]** Call `wq_login.login()` exactly ONCE before starting
   the monitor. Store the returned `client`. Do NOT call it again anywhere inside the run.

2. **[AGENT: Run decay_monitor.run_decay()]** Invoke the orchestrator:

   ```python
   import decay_monitor
   from wq_login import login

   client = login()  # ONCE — never inside the loop

   result = decay_monitor.run_decay(
       client=client,
       db_path="alpha_kb.db",   # override with --db if needed
       threshold_pct=0.15,       # override with --threshold
   )
   ```

   `run_decay()` internally:
   - Queries alphas with `status IN ('pass','ACTIVE')` only
   - Re-checks each via `trigger_correlation_check` + `poll_correlation`
   - Appends each result to `checks_history` (append-only, never overwrites)
   - Flags any alpha whose key metric dropped more than `threshold_pct` as degraded
   - Prints a CLI table and writes `alpha-kb/Decay.md`

3. **[AGENT: Handle 401]** If a `requests.exceptions.HTTPError` with status 401 is raised,
   print a clear message and stop. Do NOT attempt to re-authenticate:

   ```python
   import requests, sys
   try:
       result = decay_monitor.run_decay(...)
   except requests.exceptions.HTTPError as e:
       if getattr(getattr(e, "response", None), "status_code", None) == 401:
           print("[decay] AUTH EXPIRED — 401 received. Re-run /decay to re-authenticate.")
           sys.exit(1)
       raise
   ```

4. **[AGENT: Display results]** Present the result dict to the user:
   - `checked` — number of live alphas re-checked this run
   - `degraded` — count of alphas flagged as degraded
   - `degraded_alphas` — list of alpha_ids that crossed the threshold

---

## Flags (CLI usage)

```bash
python decay.py [--db alpha_kb.db] [--threshold 0.15]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `alpha_kb.db` | Path to alpha knowledge-base SQLite file |
| `--threshold` | `0.15` | Fractional metric drop that flags an alpha as degraded |

---

## Auth constraint (CLAUDE.md — non-negotiable)

`wq_login` is called **exactly once** before `run_decay()`. Inside the monitor there is
no auth call. This is intentional:

- Repeated biometric auth → 429 BIOMETRICS_THROTTLED (15–30 min lockout)
- A 401 inside the run means the session expired → stop cleanly, never retry
- The user controls when to re-authenticate by re-running the command

---

## No-data behavior

An alpha with fewer than 2 `checks_history` rows returns `status='no_data'`, NOT
`'degraded'`. Decay detection requires ≥2 history points before it can compare successive
runs and flag a drop. The first `/decay` run on a fresh alpha simply seeds its first
history point.

---

## Module references

- `decay_monitor.py` — `run_decay(client, db_path, threshold_pct)`, `detect_decay(conn, alpha_id, threshold_pct)`, `DEFAULT_DECAY_THRESHOLD = 0.15`
- `wq_login.py` — `login()` — single-shot biometric auth
- `grade.py` — re-check path (`trigger_correlation_check`, `poll_correlation`)
- `db.py` — `checks_history` table + `append_checks_history(conn, alpha_id, checks_list, run_tag)`
- `obsidian.py` — `write_decay_note(...)` — writes `alpha-kb/Decay.md`
