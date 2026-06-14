"""hunt.py — Orchestrator for the /hunt autonomous alpha-discovery command.

Chains: research → generate(FSA) → grade(selfcorr) → editor diagnose/mutate
→ bounded loop → returns best new submittable alpha (D-20).

Budget: configurable max_depth (generations) and max_sims ceiling.
Auth: called ONCE before the loop. A 401 mid-loop stops the run cleanly —
      never re-auth in-loop (CLAUDE.md).

Stop conditions (D-16):
  1. depth — for-loop exhausted (max_depth generations graded)
  2. budget — sims_used >= max_sims (hard ceiling, D-17)
  3. dry — no NEAR alphas after a generation (nothing to feed the next round)

Return value (D-20):
  best_submittable — alpha_id with highest Sharpe among all PASS alphas found
  best_near        — list of NEAR alpha_ids accumulated across all generations
  diversity_before/after — fsa.diversity_metric snapshots for criterion 4
"""

import argparse
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests

import db
import editor
import fsa
import grade
import ideator
import researcher
import selfcorr
from wq_login import login


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _rank_best(alpha_ids: list, conn: sqlite3.Connection) -> Optional[str]:
    """Return the alpha_id with the highest Sharpe among alpha_ids.

    Ranking criterion: Sharpe descending (D-20 — primary ranking metric).
    Alphas with NULL sharpe are sorted last.

    Args:
        alpha_ids: List of alpha_id strings to compare.
        conn: SQLite connection.

    Returns:
        Best alpha_id, or None if alpha_ids is empty.
    """
    if not alpha_ids:
        return None

    best_id = None
    best_sharpe = None

    for alpha_id in alpha_ids:
        # CR-04: only consider alphas whose persisted status is 'pass'.
        # Locally-duplicate or timeout alphas may have sharpe populated from Phase A
        # but are not submittable — exclude them from best-of ranking.
        row = conn.execute(
            "SELECT sharpe, fitness FROM alphas WHERE alpha_id=? AND status='pass' LIMIT 1",
            (alpha_id,),
        ).fetchone()
        if row is None:
            continue
        sharpe = row[0]
        if sharpe is None:
            continue
        if best_sharpe is None or sharpe > best_sharpe:
            best_sharpe = sharpe
            best_id = alpha_id

    return best_id


def _is_passable(conn: sqlite3.Connection, expr: str) -> bool:
    """Return True if expr should be queued for grading.

    An expression is passable if:
      - It is not in the DB at all (brand-new expression, not from editor path), OR
      - It is in the DB with status='queued' (pre-inserted editor stub that has not
        yet been graded).

    This filter permits editor.diagnose_and_mutate's pre-inserted stubs to pass
    through to grade_many. A blanket db.expr_exists(conn, m) is None check would
    drop ALL editor-returned mutations (all are pre-inserted as status='queued').
    """
    existing_id = db.expr_exists(conn, expr)
    if existing_id is None:
        return True  # brand-new expression (not from editor path)
    row = conn.execute(
        "SELECT status FROM alphas WHERE alpha_id=? LIMIT 1",
        (existing_id,),
    ).fetchone()
    return row is not None and row[0] == "queued"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def hunt(
    client,
    db_path: str = "alpha_kb.db",
    max_depth: int = 2,
    max_sims: int = 30,
) -> dict:
    """Autonomous alpha discovery loop (D-16/D-17/D-20).

    Chains: research → generate(FSA) → grade(selfcorr) → editor diagnose/mutate
    → bounded loop. Stops on depth OR budget OR dry-no-NEAR.

    Auth constraint: This function contains NO auth call. Auth is done exactly
    once at the CLI layer before calling hunt(). A 401 from any BRAIN call inside
    grade_many propagates up and exits the run (never re-auth in-loop, CLAUDE.md).

    Args:
        client: Authenticated BRAIN client (auth must be done once at CLI layer).
        db_path: Path to alpha_kb.db.
        max_depth: Maximum number of editor→grade generations after Gen 0.
        max_sims: Hard sim ceiling across all generations (D-17).

    Returns:
        dict with keys:
            best_submittable: alpha_id with highest Sharpe among PASS alphas, or None
            best_near: list of NEAR alpha_ids accumulated across all generations
            sims_used: total simulations executed
            run_id: 8-char hex run identifier
            generations: number of generation loops completed
            diversity_before: fsa.diversity_metric snapshot before first grade_many
            diversity_after: fsa.diversity_metric snapshot after final generation
    """
    conn = db.init_db(db_path)

    try:
        run_id = str(uuid.uuid4())[:8]
        sims_used = 0
        best_submittable = None
        best_near: list = []
        all_pass_ids: list = []

        # WR-04: insert a runs row so select_archetype cycles archetypes correctly
        # (researcher.select_archetype counts rows in the runs table to pick the archetype).
        # num_pass / iterations are updated before returning.
        thesis_placeholder = ""  # filled after thesis is built below
        conn.execute(
            "INSERT OR IGNORE INTO runs (run_id, thesis, started_at, iterations, num_pass) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, thesis_placeholder, datetime.now(timezone.utc).isoformat(), 0, 0),
        )
        conn.commit()

        # One-time backfill before loop — builds PnL reference set for selfcorr.
        # Must be sequential (not inside ≤3-concurrent sim pool). CLAUDE.md constraint.
        print(f"[hunt] run_id={run_id} — backfilling active PnL cache...")
        selfcorr.backfill_active_pnl(client, conn, db_path)

        # Snapshot structural diversity BEFORE (criterion 4 baseline)
        diversity_before = fsa.diversity_metric(conn)

        # Mine frequent motifs once per run (avoid-list for FSA steer + hard gate)
        avoid_motifs = fsa.mine_frequent_motifs(conn)

        # Gen 0: Researcher → Ideator → FSA filter → grade
        print(f"[hunt] Gen 0 — researching thesis...")
        thesis = researcher.build_thesis(conn, avoid_motifs=avoid_motifs)

        # WR-04: update runs row with the actual thesis archetype
        thesis_summary = thesis.get("archetype", "")
        conn.execute(
            "UPDATE runs SET thesis=? WHERE run_id=?",
            (thesis_summary, run_id),
        )
        conn.commit()

        print(f"[hunt] Gen 0 — generating candidates (archetype={thesis.get('archetype','?')})...")
        candidates = ideator.generate_candidates(conn, thesis)

        # FSA filter — convert to dicts for filter API (mirrors find_alphas.py lines 409-411)
        cand_dicts = [{"expression": c.get("expression", ""), **c} for c in candidates]
        filtered = fsa.filter_candidates(cand_dicts, avoid_motifs)

        # queueable gate — drops expressions that fail local validate or are already graded
        queue = [c["expression"] for c in ideator.queueable(filtered)]

        # CR-05: enforce max_sims hard ceiling on Gen 0 (D-17).
        # Mutation generations trim their queue to the remaining budget; Gen 0 must too.
        queue = queue[:max_sims - sims_used]

        print(f"[hunt] Gen 0 — grading {len(queue)} candidates (max_workers=3)...")
        results = grade.grade_many(
            client, conn, queue, run_id,
            max_workers=3, db_path=db_path,
        )
        # WR-09: count only actual simulations — skip duplicate/invalid/error results
        # (those never consumed a BRAIN sim slot)
        sims_used += sum(
            1 for r in results
            if r.get("status") not in ("duplicate", "invalid", "error")
        )

        # Loop: editor → mutate → grade (D-16/D-17)
        gen = -1  # will be set to 0 on first iteration
        for gen in range(max_depth):
            # Reclassify all graded results
            near_ids: list = []
            pass_ids: list = []

            for r in results:
                alpha_id = r.get("alpha_id")
                if not alpha_id:
                    continue
                # CR-02: only classify results that completed grading (pass or fail status)
                # Skip duplicate/error/timeout/invalid — those stubs/errors should not
                # pollute pass_ids or near_ids.
                if r.get("status") not in ("pass", "fail"):
                    continue
                status, _ = editor.classify_from_checks(alpha_id, conn)
                if status == "near":
                    near_ids.append(alpha_id)
                    # WR-05: persist 'near' status so /iterate can query it directly
                    conn.execute(
                        "UPDATE alphas SET status='near' WHERE alpha_id=?", (alpha_id,)
                    )
                elif status == "pass":
                    pass_ids.append(alpha_id)

            conn.commit()  # flush WR-05 near-status updates
            # Accumulate PASS across generations for best-of ranking
            all_pass_ids.extend(pass_ids)
            best_submittable = _rank_best(all_pass_ids, conn)
            best_near.extend(near_ids)

            print(
                f"[hunt] Gen {gen} — pass={len(pass_ids)} near={len(near_ids)} "
                f"sims_used={sims_used}/{max_sims}"
            )

            # Stop conditions (D-16)
            if sims_used >= max_sims:
                print("[hunt] budget exhausted — stopping")
                break
            if not near_ids:
                print("[hunt] no NEAR alphas to mutate — stopping (dry)")
                break

            # Collect mutations from NEAR and FAIL alphas
            all_mutations: list = []
            parent_map: dict = {}  # WR-01: track mutation → parent lineage
            for r in results:
                alpha_id = r.get("alpha_id")
                if not alpha_id:
                    continue
                # CR-02: only classify completed-grading results
                if r.get("status") not in ("pass", "fail"):
                    continue
                # classify to determine eligibility
                status, _ = editor.classify_from_checks(alpha_id, conn)
                if status in ("near", "fail"):
                    ed = editor.diagnose_and_mutate(alpha_id, conn, avoid_motifs=avoid_motifs)
                    mutations = ed.get("mutations", [])
                    all_mutations.extend(mutations)
                    # WR-01: record parent lineage for grade_many
                    for m in mutations:
                        parent_map[m] = alpha_id

            if not all_mutations:
                print("[hunt] no mutations produced — stopping")
                break

            # Filter mutations:
            # Use _is_passable() — NOT a blanket db.expr_exists is None check.
            # editor.diagnose_and_mutate pre-inserts each mutation as status='queued',
            # so a blanket check would drop 100% of editor-returned mutations.
            all_mutations = [m for m in all_mutations if _is_passable(conn, m)]

            # Apply FSA structural filter on top of passability filter
            mut_dicts = [{"expression": m} for m in all_mutations]
            mut_dicts = fsa.filter_candidates(mut_dicts, avoid_motifs)

            # Trim to remaining sim budget
            queue_next = [d["expression"] for d in mut_dicts][: max_sims - sims_used]

            if not queue_next:
                print("[hunt] no passable mutations after FSA filter — stopping")
                break

            print(f"[hunt] Gen {gen} → Gen {gen+1} — grading {len(queue_next)} mutations...")
            # WR-01: pass parent_map so grade_many can forward parent_alpha_id to grade_one.
            # Mutations are already in DB as status='queued' stubs with parent_alpha_id
            # set by editor.diagnose_and_mutate. CR-01 in grade_one replaces the stub
            # with the real graded row at simulation time.
            results = grade.grade_many(
                client, conn, queue_next, run_id,
                max_workers=3, db_path=db_path,
                parent_map=parent_map,
            )
            # WR-09: count only actual simulations (not duplicate/invalid/error skips)
            sims_used += sum(
                1 for r in results
                if r.get("status") not in ("duplicate", "invalid", "error")
            )

        # Final pass: reclassify last generation's results (if any)
        # WR-03: also collect NEAR alphas from the final generation into best_near
        if results:
            for r in results:
                alpha_id = r.get("alpha_id")
                if not alpha_id:
                    continue
                # CR-02: only classify completed-grading results
                if r.get("status") not in ("pass", "fail"):
                    continue
                status, _ = editor.classify_from_checks(alpha_id, conn)
                if status == "pass" and alpha_id not in all_pass_ids:
                    all_pass_ids.append(alpha_id)
                elif status == "near" and alpha_id not in best_near:
                    # WR-03: collect NEAR from final generation (WR-05: persist status)
                    best_near.append(alpha_id)
                    conn.execute(
                        "UPDATE alphas SET status='near' WHERE alpha_id=?", (alpha_id,)
                    )
            conn.commit()  # flush final-pass near-status updates
            best_submittable = _rank_best(all_pass_ids, conn)

        # Snapshot structural diversity AFTER final generation (criterion 4)
        diversity_after = fsa.diversity_metric(conn)
        print(
            f"[hunt] diversity before: {diversity_before['top_motif_share']:.2%} | "
            f"after: {diversity_after['top_motif_share']:.2%}"
        )

        generations_count = gen + 1 if gen >= 0 else 0

        # WR-04: update runs row with final num_pass and iterations before returning
        conn.execute(
            "UPDATE runs SET num_pass=?, iterations=? WHERE run_id=?",
            (len(all_pass_ids), generations_count, run_id),
        )
        conn.commit()

        result = {
            "best_submittable": best_submittable,
            "best_near": best_near,
            "sims_used": sims_used,
            "run_id": run_id,
            "generations": generations_count,
            "diversity_before": diversity_before,
            "diversity_after": diversity_after,
        }

    finally:
        conn.close()

    # Human-readable summary (mirrors find_alphas.py lines 454-463)
    print(f"\n--- /hunt complete ---")
    print(f"  run_id:           {result['run_id']}")
    print(f"  sims used:        {result['sims_used']} / {max_sims}")
    print(f"  generations:      {result['generations']}")
    print(f"  best submittable: {result['best_submittable']}")
    print(f"  best NEAR:        {len(result['best_near'])} candidates")

    return result


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Autonomous alpha discovery loop (/hunt)."
    )
    parser.add_argument(
        "--db",
        default="alpha_kb.db",
        help="Path to alpha_kb.db (default: alpha_kb.db)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=2,
        help="Max editor→grade generations after Gen 0 (default: 2)",
    )
    parser.add_argument(
        "--max-sims",
        type=int,
        default=30,
        help="Hard simulation ceiling across all generations (default: 30)",
    )
    args = parser.parse_args()

    # Single-shot auth — called ONCE before the loop (CLAUDE.md constraint).
    # A 401 inside hunt() propagates here and exits cleanly (never re-auth in-loop).
    print("[hunt] logging in...")
    client = login()
    print("[hunt] authenticated")

    try:
        result = hunt(
            client=client,
            db_path=args.db,
            max_depth=args.max_depth,
            max_sims=args.max_sims,
        )
    except editor.EditorAuthError as e:
        # WR-08: Claude CLI auth failure — NOT a BRAIN session expiry.
        # Do NOT suggest BRAIN re-auth (risks 429 BIOMETRICS_THROTTLED lockout per CLAUDE.md).
        print(f"[hunt] CLAUDE CLI AUTH FAILURE — {e}")
        print("[hunt] Fix: run 'claude login' to re-authenticate the Claude CLI.")
        print("[hunt] This is NOT a BRAIN session expiry — do NOT re-run hunt.py for BRAIN auth.")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        if getattr(getattr(e, "response", None), "status_code", None) == 401:
            print(
                "[hunt] BRAIN AUTH EXPIRED — 401 received. "
                "Re-run hunt.py to re-authenticate with BRAIN. Stopping."
            )
            sys.exit(1)
        raise
