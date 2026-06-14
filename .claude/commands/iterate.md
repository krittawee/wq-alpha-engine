# /iterate — Standalone Editor Entry Point

Loads already-graded NEAR and FAIL alphas from the DB, calls
`editor.diagnose_and_mutate` on each, displays diagnosis and proposed mutations,
and optionally queues valid mutations for grading via `grade.grade_many`.

**Use this command after `/hunt` to target NEAR alphas for manual mutation cycles,
or after `python cli.py` grading runs when you want to refine specific alphas.**

---

## What this command does

1. **[AGENT: Load NEAR/FAIL alphas from DB]** Query the `alphas` table:

   ```python
   import db, sqlite3

   conn = db.init_db("alpha_kb.db")
   rows = conn.execute(
       "SELECT alpha_id, expression, sharpe, status "
       "FROM alphas "
       "WHERE status IN ('near', 'fail') "
       "ORDER BY sharpe DESC NULLS LAST "
       "LIMIT 20"
   ).fetchall()
   ```

   Present a table of NEAR/FAIL alphas to the user (alpha_id, expression, sharpe, status).

2. **[AGENT: Run editor.diagnose_and_mutate]** For each selected alpha (or all, if user says "all"):

   ```python
   import editor, fsa

   avoid_motifs = fsa.mine_frequent_motifs(conn)

   for alpha_id in selected_ids:
       result = editor.diagnose_and_mutate(
           alpha_id, conn, avoid_motifs=avoid_motifs
       )
       print(f"Alpha: {alpha_id}")
       print(f"  Status:    {result['status']}")
       print(f"  Diagnosis: {result['diagnosis']}")
       print(f"  Mutations: {result['mutations']}")
   ```

   The result dict contains:
   - `alpha_id`: the input alpha
   - `status`: classification ('pass' | 'near' | 'fail')
   - `diagnosis`: human-readable explanation of what checks failed and why
   - `mutations`: list of validated expression strings (already pre-inserted as status='queued')

3. **[AGENT: Display results for human review]** Present:
   - Diagnosis text for each alpha
   - Proposed mutation expressions
   - Check failures that motivated each mutation

4. **[AGENT: Optional — queue mutations for grading]** If the user confirms, grade the mutations:

   ```python
   import grade
   from wq_login import login

   # Collect all mutation expressions from all diagnose_and_mutate results
   all_mutations = []
   for result in editor_results:
       all_mutations.extend(result["mutations"])

   # Auth — called ONCE before grading (never inside loop)
   client = login()

   import uuid
   run_id = str(uuid.uuid4())[:8]

   graded = grade.grade_many(
       client, conn, all_mutations, run_id,
       max_workers=3, db_path="alpha_kb.db",
   )
   ```

   Note: `editor.diagnose_and_mutate` already pre-inserts mutations as status='queued'
   stubs with `parent_alpha_id` set. `grade.grade_many` finds each expression via
   `db.expr_exists` and updates in place (status, sharpe, fitness, checks).

---

## Auth constraint (CLAUDE.md — non-negotiable)

If grading mutations: call `wq_login.login()` **exactly once** before `grade.grade_many`.
Do NOT call it inside any loop. A 401 from `grade_many` means the session expired —
stop cleanly, never retry.

---

## Concurrency constraint (CLAUDE.md — non-negotiable)

Always call `grade.grade_many` with `max_workers=3` (BRAIN concurrent slot cap).
Never raise this value.

---

## NEAR vs FAIL targeting

| Status | Description | Editor action |
|--------|-------------|---------------|
| `near` | ≤2 failing checks, all gaps ≤20% | High-value target — mutations likely to reach PASS |
| `fail` | Hard-fail checks or >2 failures | Lower value — mutate to escape structural trap |

Prioritise NEAR alphas — they are closest to submittable (D-05..D-07 classification).

---

## FSA steering

`fsa.mine_frequent_motifs(conn)` is called before mutation to inject the avoid-list
into the editor's LLM prompt. This steers mutations away from overrepresented structural
patterns in the current PASS alpha pool (D-14, D-15).

---

## Module references

- `editor.py` — `classify_from_checks(alpha_id, conn)`, `diagnose_and_mutate(alpha_id, conn, avoid_motifs=...)`
- `fsa.py` — `mine_frequent_motifs(conn)`, `filter_candidates(candidates, avoid_motifs)`
- `grade.py` — `grade_many(client, conn, expressions, run_id, max_workers=3, db_path=db_path)`
- `db.py` — `init_db(path)`, `expr_exists(conn, expr)`
- `wq_login.py` — `login()` — single-shot auth (call once before grading)

---

## Output

After running:

1. **Diagnosis table** — per-alpha: status, which checks failed, gap magnitude
2. **Mutation list** — validated expression strings for each alpha
3. **Optional grading results** — if user confirms, sharpe/fitness for each mutation
4. **DB** — mutations written to `alphas` with parent_alpha_id linkage and `checks` filled
