# /show-results — Alpha Results Viewer + Performance Comparison

Show graded alphas from `alpha_kb.db` as a ranked table. Default mode is a pure local
DB read (no login, no BRAIN calls). With `--live` it logs in ONCE and fills the
**BOOK_Δ** column — BRAIN's Performance Comparison "Change (Before − After submission)",
i.e. how much submitting each alpha would move your competition score.

**Auth: `--live` calls `wq_login` exactly ONCE. Default mode makes no BRAIN call at all.
Never re-auth in-loop (CLAUDE.md lockout constraint).**

---

## What this command does

1. **[AGENT: Run the viewer]** Invoke the script with any flags the user passed:

   ```bash
   python show_results.py [--db alpha_kb.db] [--status pass|near|fail|queued]
                          [--delay 0|1] [--sort sharpe|fitness|self_corr|prod_corr]
                          [--limit N] [--live] [--competition IQC2026S2]
   ```

   Default (no `--live`): reads `alpha_kb.db` and prints a ranked table —
   `RANK · ALPHA_ID · SHARPE · DELAY · STATUS · SELF_CORR · PROD_CORR · FITNESS · BOOK_Δ`.
   `BOOK_Δ` shows `-` unless `--live` is passed.

2. **[AGENT: --live BOOK_Δ]** When the user wants the Performance Comparison numbers,
   add `--live`. The script logs in once (reusing the cached `.wq_session.json` when
   valid — no biometric), then GETs
   `/competitions/{competition}/alphas/{id}/before-and-after-performance` per alpha and
   fills `BOOK_Δ` from `score.after − score.before`.
   - **Negative BOOK_Δ** = submitting HURTS the book (too correlated — drops the score).
   - **Positive BOOK_Δ** = the alpha ADDS to the team score (decorrelated / additive).

3. **[AGENT: Confirm one alpha's raw response]** To verify the endpoint/field mapping for
   a single alpha (prints raw JSON + parsed before/after/change):

   ```bash
   python show_results.py --debug-json <alpha_id>
   ```

4. **[AGENT: Display]** Present the table. Call out which alphas are both PASS and
   BOOK_Δ-positive — those are submit-ready AND additive (the v1.1 goal). Remember:
   higher Sharpe does NOT mean higher BOOK_Δ; a lower-Sharpe decorrelated alpha can add
   more than a high-Sharpe correlated one.

---

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `alpha_kb.db` | SQLite knowledge-base path |
| `--status` | *(all)* | Filter by status: `pass` \| `near` \| `fail` \| `queued` |
| `--delay` | *(both)* | Filter by delay: `0` or `1` |
| `--sort` | `sharpe` | Sort key (desc, NULLs last): `sharpe` \| `fitness` \| `self_corr` \| `prod_corr` |
| `--limit` | `30` | Max rows |
| `--live` | off | Log in once and fill BOOK_Δ from BRAIN's Performance Comparison |
| `--competition` | `IQC2026S2` | Competition id used by `--live` |
| `--debug-json <id>` | — | Fetch + print one alpha's raw before-and-after JSON (needs login) |

---

## BOOK_Δ — what it is

BRAIN's Performance Comparison panel shows your competition Score **Before** vs **After**
submitting an alpha, and the **Change**. `BOOK_Δ` is that Change. It is the truest measure
of additivity: not "does it pass the checks" but "does it improve my standing." The local
proxy for it is `SELF_CORRELATION` (lower = more additive); `--live` fetches the real number.

---

## Auth & concurrency constraints (CLAUDE.md — non-negotiable)

- `--live` calls `wq_login.login()` **once**; the per-alpha fetches are read-only GETs (not
  simulations). A 401 stops the run cleanly — never re-authenticate in-loop.
- These are catalog/score reads, not sims, so the ≤3 concurrent-sim cap does not apply, but
  BRAIN rate-limits these reads — the script retries/handles empty bodies per alpha.

---

## Module references

- `show_results.py` — `main()`, `fetch_before_after(client, alpha_id, competition)`,
  `extract_score_change(data)` (reads `score.before` / `score.after`)
- `wq_login.py` — `login()` — single-shot biometric auth (only used with `--live`)
- `db.py` — `alpha_kb.db` `alphas` table (read-only)

---

## Output

1. Ranked table of graded alphas (id, sharpe, delay, status, self/prod corr, fitness, BOOK_Δ)
2. With `--live`: real BOOK_Δ per alpha (`+` adds to book / `-` hurts it / `err` if not fetchable)
3. No DB writes — this command only reads `alpha_kb.db` and (with `--live`) BRAIN scores
