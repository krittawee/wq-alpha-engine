"""bruteforce.py — AI-free brute-force alpha discovery engine (Tool B).

Enumerate parameterized templates, validate locally, probe-sim a spread sample,
bulk-sim survivors at ≤3 concurrent, gate through additivity, record failure aggregates.
No external model dependencies. Single-shot auth; 401 stops cleanly without re-auth.

Public API:
    settings_grid_for_archetype(archetype: str) -> list[dict]
    bruteforce(client, db_path, delay, quota, probe_size, template_names, generated_templates) -> dict
"""

import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

import requests.exceptions

import additivity
import db
import editor
import grade
import probe_delay
import selfcorr
import templates
import validate
from grade import _BASE_SETTINGS
from optimizer import ARCHETYPE_HEURISTICS


# ---------------------------------------------------------------------------
# Settings grid builder (D-04)
# ---------------------------------------------------------------------------


def settings_grid_for_archetype(archetype: str) -> list:
    """Return a list of full settings dicts for the given archetype.

    Builds one settings dict per (decay, neutralization, truncation) combo in
    ARCHETYPE_HEURISTICS for the given archetype. Falls back to "reversal" when
    the archetype is unknown.

    NOTE: "regular" key is intentionally never included — buggy simulate() param
    (project constraint). Only decay, neutralization, truncation are overridden.

    DELAY NOTE: each dict inherits delay from _BASE_SETTINGS (=1). Callers that run
    at a non-default delay MUST stamp the run's delay into the returned dict before
    passing it to grade (see _run_template). settings["delay"] takes precedence over
    grade_one's delay= argument, so a stale delay here silently overrides the request.

    Args:
        archetype: Key into ARCHETYPE_HEURISTICS (e.g. "reversal", "momentum").

    Returns:
        List of full settings dicts (one per heuristic combo).
    """
    combos = ARCHETYPE_HEURISTICS.get(archetype, ARCHETYPE_HEURISTICS["reversal"])
    result = []
    for decay, neutralization, truncation in combos:
        s = dict(_BASE_SETTINGS)
        s["decay"] = decay
        s["neutralization"] = neutralization
        s["truncation"] = truncation
        result.append(s)
    return result


# ---------------------------------------------------------------------------
# Private: quota-aware concurrent bulk simulator (D-07)
# ---------------------------------------------------------------------------


def _bulk_sim_quota_aware(
    client,
    db_path: str,
    combos: list,
    run_id: str,
    quota_remaining: int,
    delay: int,
) -> dict:
    """Submit all combos to BRAIN concurrently (≤3 workers); stop when quota fills.

    Submits all (expr, settings_dict) pairs via ThreadPoolExecutor(max_workers=3).
    Drains results via as_completed — checks quota after EACH future resolves and
    shuts the executor down immediately when quota_remaining <= 0.

    Args:
        client: Authenticated BRAIN client.
        db_path: Path to alpha_kb.db (each worker opens its own connection).
        combos: List of (expression_str, settings_dict) tuples to grade.
        run_id: Current run identifier (written to alphas rows).
        quota_remaining: Stop after this many additive survivors.
        delay: Simulation delay in days.

    Returns:
        {"results": list[dict], "hit_401": bool}
        results: grade_one return dicts for every completed future.
        hit_401: True when an HTTPError(401) was detected (caller handles exit).
    """
    results = []
    hit_401 = False

    def _worker(expr, settings_dict):
        """Open own conn, call grade_one, close conn. Re-raises HTTPError(401)."""
        worker_conn = db.init_db(db_path)
        try:
            return grade.grade_one(
                client, worker_conn, expr, run_id,
                settings=settings_dict, delay=delay,
            )
        except requests.exceptions.HTTPError as e:
            if getattr(getattr(e, "response", None), "status_code", None) == 401:
                raise  # propagate auth expiry immediately
            # Other HTTP errors: return as error result
            return {"expression": expr, "status": "error", "alpha_id": None, "error": str(e)}
        except Exception as e:
            return {"expression": expr, "status": "error", "alpha_id": None, "error": str(e)}
        finally:
            worker_conn.close()

    with ThreadPoolExecutor(max_workers=3) as executor:
        # Submit all combos individually
        future_to_expr = {
            executor.submit(_worker, expr, settings_dict): expr
            for expr, settings_dict in combos
        }
        for future in as_completed(future_to_expr):
            try:
                result = future.result()
            except requests.exceptions.HTTPError as e:
                if getattr(getattr(e, "response", None), "status_code", None) == 401:
                    hit_401 = True
                    executor.shutdown(wait=False)
                    break
                # Non-401 HTTP error
                expr = future_to_expr[future]
                result = {"expression": expr, "status": "error", "alpha_id": None, "error": str(e)}
            except Exception as e:
                expr = future_to_expr[future]
                result = {"expression": expr, "status": "error", "alpha_id": None, "error": str(e)}
            results.append(result)
            # Check quota — stop draining when no remaining budget
            if quota_remaining <= 0:
                executor.shutdown(wait=False)
                break

    return {"results": results, "hit_401": hit_401}


# ---------------------------------------------------------------------------
# Private: run one template through the full pipeline
# ---------------------------------------------------------------------------


def _run_template(
    client,
    conn,
    db_path: str,
    template: dict,
    run_id: str,
    quota_remaining: int,
    delay: int,
    probe_size: int,
    max_sims_remaining: Optional[int] = None,
) -> dict:
    """Run the full validate → probe → bulk-sim → additivity pipeline for one template.

    Implements the Architecture Diagram from 07-RESEARCH.md:
      expand_slots → validate gate → probe/abandon → bulk-sim (quota-aware)
      → additivity gate → return aggregate counters.

    Args:
        client: Authenticated BRAIN client.
        conn: SQLite connection for this template's execution.
        db_path: File path for worker connections in bulk-sim.
        template: Template dict from templates.TEMPLATES.
        run_id: Current run identifier.
        quota_remaining: Additive survivors still needed to hit quota.
        delay: Simulation delay in days.
        probe_size: Max probe sample size (default 5).
        max_sims_remaining: Optional hard cap on sims this template may enqueue.

    Returns:
        Dict with keys: n_combos, n_validated, n_probed, n_simmed, n_survivors,
        n_additive, probe_abandoned, hit_401, additive_alpha_ids, failure_counts,
        examples.
    """
    name = template.get("name", "unknown")
    archetype = template.get("settings_archetype", "reversal")

    # Counters and accumulators
    failure_counts: dict = {}
    examples: dict = {}
    additive_alpha_ids: list = []

    def _bump_failure(key: str, example: Optional[str] = None) -> None:
        failure_counts[key] = failure_counts.get(key, 0) + 1
        if example is not None:
            bucket = examples.setdefault(key, [])
            if len(bucket) < 3:
                bucket.append(example)

    # --- Step 1: expand slots ---
    combos_all = templates.expand_slots(conn, template)
    n_combos = len(combos_all)

    # --- Step 2: validate gate ---
    valid_combos = []
    for expr, slot_vals in combos_all:
        ok, reason = validate.validate(conn, expr)
        if ok:
            valid_combos.append((expr, slot_vals))
        else:
            _bump_failure("validate_dropped", expr)

    n_validated = len(valid_combos)

    # --- Step 3: early exit if nothing passed validation ---
    if not valid_combos:
        return {
            "n_combos": n_combos,
            "n_validated": 0,
            "n_probed": 0,
            "n_simmed": 0,
            "n_survivors": 0,
            "n_additive": 0,
            "probe_abandoned": True,
            "hit_401": False,
            "additive_alpha_ids": [],
            "failure_counts": failure_counts,
            "examples": examples,
        }
    if max_sims_remaining is not None and max_sims_remaining <= 0:
        return {
            "n_combos": n_combos,
            "n_validated": n_validated,
            "n_probed": 0,
            "n_simmed": 0,
            "n_survivors": 0,
            "n_additive": 0,
            "probe_abandoned": True,
            "hit_401": False,
            "additive_alpha_ids": [],
            "failure_counts": failure_counts,
            "examples": examples,
        }

    # --- Step 4: probe sample ---
    slot_names = list(template.get("slots", {}).keys())
    probe_cap = probe_size
    if max_sims_remaining is not None:
        probe_cap = min(probe_cap, max_sims_remaining)
    sample = templates.probe_spread_sample(valid_combos, slot_names, size=probe_cap)
    n_probed = len(sample)

    # Build probe settings from archetype (first combo in grid).
    # CRITICAL (delay bug fix): stamp the run's requested delay into the settings dict.
    # settings_grid_for_archetype inherits delay=1 from _BASE_SETTINGS, and grade_one
    # gives settings["delay"] precedence over the delay= argument. Without this stamp,
    # a `--delay 0` run is silently dropped and every sim runs at delay=1 (root cause of
    # the "delay=0 ignored" + downstream sim errors observed in /tmp/bf_verify.log).
    probe_settings = settings_grid_for_archetype(archetype)[0]
    probe_settings["delay"] = delay

    # Call grade_many for the bounded probe (max probe_size items).
    # Expressions MUST be plain strings: grade_many reads a tuple's 2nd element as
    # parent_alpha_id, so passing (expr, settings) made the settings dict get bound
    # as a SQL parameter → "Error binding parameter 3: type 'dict' is not supported"
    # and every probe sim returned status="error". Settings are delivered solely via
    # settings_map (expression → delay-stamped settings dict), which is the supported
    # channel; parent_alpha_id stays None for fresh template combos.
    probe_exprs = [e for e, _ in sample]
    probe_settings_map = {e: probe_settings for e, _ in sample}
    probe_results = grade.grade_many(
        client,
        conn,
        probe_exprs,
        run_id,
        max_workers=min(3, max(1, len(sample))),
        db_path=db_path,
        settings_map=probe_settings_map,
        delay=delay,
    )

    # --- Step 5: probe verdict (D-05) ---
    # Template survives if ANY probe has status "pass" or classify_from_checks returns "near"/"pass".
    # If ALL probes are far-fail or error, abandon template.
    probe_survived = False
    probed_exprs_set = set()
    for r in probe_results:
        expr = r.get("expression", "")
        probed_exprs_set.add(expr)
        status = r.get("status", "error")
        alpha_id = r.get("alpha_id")

        if status == "error":
            # Surface the real error message so abandoned-template failures are debuggable
            # (previously only the expression was stored, hiding BRAIN/sim error bodies).
            err = r.get("error")
            example = f"{expr} :: {err}" if err else expr
            _bump_failure("sim_error", example)
            continue

        if alpha_id:
            class_status, _ = editor.classify_from_checks(alpha_id, conn)
            if class_status in ("pass", "near"):
                probe_survived = True
        elif status in ("pass",):
            probe_survived = True

    if not probe_survived:
        print(f"[bruteforce] template abandoned after probe: {name}")
        return {
            "n_combos": n_combos,
            "n_validated": n_validated,
            "n_probed": n_probed,
            "n_simmed": 0,
            "n_survivors": 0,
            "n_additive": 0,
            "probe_abandoned": True,
            "hit_401": False,
            "additive_alpha_ids": [],
            "failure_counts": failure_counts,
            "examples": examples,
        }

    # --- Step 6: bulk-sim survivors (valid combos minus those already probed) ---
    bulk_combos = [
        (expr, dict(probe_settings))  # reuse probe_settings (delay-stamped) for bulk
        for expr, _ in valid_combos
        if expr not in probed_exprs_set
    ]
    if max_sims_remaining is not None:
        bulk_cap = max(0, max_sims_remaining - n_probed)
        bulk_combos = bulk_combos[:bulk_cap]

    bulk_result = _bulk_sim_quota_aware(
        client, db_path, bulk_combos, run_id, quota_remaining, delay
    )
    bulk_results = bulk_result["results"]
    hit_401 = bulk_result["hit_401"]

    # --- Step 7: classify bulk results ---
    is_pass_ids = []
    n_simmed = n_probed  # probe sims count
    for r in bulk_results:
        n_simmed += 1
        status = r.get("status", "error")
        alpha_id = r.get("alpha_id")
        expr = r.get("expression", "")

        if status == "error":
            err = r.get("error")
            example = f"{expr} :: {err}" if err else expr
            _bump_failure("sim_error", example)
        elif status == "pass":
            is_pass_ids.append(alpha_id)
        elif status in ("fail", "duplicate", "coerced", "invalid"):
            # Track IS_fail with check name when available
            checks = r.get("checks", [])
            fail_names = [c.get("name", "UNKNOWN") for c in checks if c.get("result") == "FAIL"]
            if fail_names:
                for fname in fail_names:
                    _bump_failure(f"IS_fail_{fname}", expr)
            else:
                _bump_failure("IS_fail", expr)

    # Also collect IS-passing alphas from probe results
    for r in probe_results:
        status = r.get("status", "error")
        alpha_id = r.get("alpha_id")
        if status == "pass" and alpha_id and alpha_id not in is_pass_ids:
            is_pass_ids.append(alpha_id)

    n_survivors = len(is_pass_ids)

    # Early return on 401 (caller will handle clean-stop)
    if hit_401:
        return {
            "n_combos": n_combos,
            "n_validated": n_validated,
            "n_probed": n_probed,
            "n_simmed": n_simmed,
            "n_survivors": n_survivors,
            "n_additive": 0,
            "probe_abandoned": False,
            "hit_401": True,
            "additive_alpha_ids": [],
            "failure_counts": failure_counts,
            "examples": examples,
        }

    # --- Step 8: per-template additivity gate ---
    n_additive = 0
    if is_pass_ids:
        pass_candidates = []
        for aid in is_pass_ids:
            row = conn.execute(
                "SELECT pnl_path FROM alphas WHERE alpha_id=?", (aid,)
            ).fetchone()
            pass_candidates.append({"alpha_id": aid, "pnl_path": row[0] if row else None})

        ranked = additivity.rank_by_proxy(pass_candidates, conn)
        proxy_survivors = [r for r in ranked if not r.proxy_drop]

        for r in proxy_survivors[:additivity.CONFIRM_LIMIT]:
            result = additivity.confirm_additive(client, r.alpha_id, conn)
            if result.additive is True:
                additive_alpha_ids.append(r.alpha_id)
                n_additive += 1
            else:
                _bump_failure("gate_fail_correlated", r.alpha_id)

    # --- Step 9: return aggregate counters ---
    return {
        "n_combos": n_combos,
        "n_validated": n_validated,
        "n_probed": n_probed,
        "n_simmed": n_simmed,
        "n_survivors": n_survivors,
        "n_additive": n_additive,
        "probe_abandoned": False,
        "hit_401": False,
        "additive_alpha_ids": additive_alpha_ids,
        "failure_counts": failure_counts,
        "examples": examples,
    }


# ---------------------------------------------------------------------------
# Public: main engine entry point
# ---------------------------------------------------------------------------


def bruteforce(
    client,
    db_path: str = "alpha_kb.db",
    delay: int = 0,
    quota: int = 5,
    probe_size: int = 5,
    template_names: Optional[list] = None,
    generated_templates: Optional[list] = None,
    max_sims: Optional[int] = None,
) -> dict:
    """Brute-force alpha discovery engine (Tool B).

    Pipeline per template:
      enumerate combos → validate-filter → probe/abandon → quota-aware bulk-sim
      → per-template additivity gate → failure persistence → quota stop or dry.

    Auth constraint: This function contains NO auth call. Auth must be done exactly
    once at the CLI layer before calling bruteforce(). A 401 from any BRAIN call
    stops the run cleanly with sys.exit(1) — never re-auth in-loop (project constraint).

    Args:
        client: Authenticated BRAIN client (auth done once at CLI layer).
        db_path: Path to alpha_kb.db.
        delay: Simulation delay in days (0 = default for Tool B).
        quota: Stop after this many additive survivors are found.
        probe_size: Max combos to probe per template (default 5).
        template_names: If provided, only run templates with these names.
        generated_templates: Optional runtime template dicts from /hunt handoff.
            Each may include generated_template_id for bruteforce_runs linkage.
        max_sims: Optional hard ceiling across probe + bulk expressions for this call.

    Returns:
        dict with keys:
            quota_count: Number of confirmed-additive survivors found.
            n_templates_done: Number of templates fully processed.
            stop_reason: "quota_met" | "sim_budget" | "dry" (loop exhausted).
            additive_ids: List of confirmed-additive alpha_ids.
            sims_used: Actual grade_many simulations counted by the engine.
    """
    conn = db.init_db(db_path)
    run_id = str(uuid.uuid4())

    # Insert a runs row so the run is tracked even if we exit early
    thesis = f"bruteforce delay={delay} quota={quota}"
    conn.execute(
        "INSERT OR IGNORE INTO runs (run_id, thesis, started_at, iterations, num_pass) "
        "VALUES (?, ?, ?, ?, ?)",
        (run_id, thesis, datetime.now(timezone.utc).isoformat(), 0, 0),
    )
    conn.commit()

    # One-time PnL backfill before loop (sequential, concurrency constraint)
    print(f"[bruteforce] run_id={run_id} — backfilling active PnL cache...")
    selfcorr.backfill_active_pnl(client, conn, db_path)

    # D-08: probe delay gate (skip for default delay=1 to avoid wasting a sim slot)
    if delay != 1:
        print(f"[bruteforce] delay={delay} — running probe_and_gate before main loop...")
        probe_delay.probe_and_gate(client, conn, requested_delay=delay)
        print(f"[bruteforce] probe passed — BRAIN confirmed delay={delay}")

    # Determine which templates to run. Generated templates bypass the static
    # registry but still use the same validate/probe/bulk/additivity engine.
    if generated_templates is not None:
        templates_to_run = list(generated_templates)
    else:
        templates_to_run = [
            t for t in templates.TEMPLATES
            if template_names is None or t["name"] in template_names
        ]

    quota_count = 0
    n_templates_done = 0
    n_simmed_total = 0
    additive_ids: list = []
    stop_reason = "dry"

    try:
        for template in templates_to_run:
            if max_sims is not None and n_simmed_total >= max_sims:
                stop_reason = "sim_budget"
                break
            tname = template.get("name", "unknown")
            started_at_t = datetime.now(timezone.utc).isoformat()

            # Insert a placeholder bruteforce_runs row; update at end of template
            rowid = db.insert_bruteforce_run(conn, {
                "run_id": run_id,
                "template_name": tname,
                "generated_template_id": template.get("generated_template_id"),
                "delay": delay,
                "quota_target": quota,
                "started_at": started_at_t,
                "partial": 0,
                "quota_hit": 0,
                "n_combos": 0,
                "n_validated": 0,
                "n_probed": 0,
                "n_simmed": 0,
                "n_survivors": 0,
                "n_additive": 0,
            })

            print(f"[bruteforce] template: {tname} (quota remaining: {quota - quota_count})")

            try:
                tr = _run_template(
                    client, conn, db_path, template, run_id,
                    quota_remaining=quota - quota_count,
                    delay=delay,
                    probe_size=probe_size,
                    max_sims_remaining=None if max_sims is None else max_sims - n_simmed_total,
                )
            except requests.exceptions.HTTPError as e:
                if getattr(getattr(e, "response", None), "status_code", None) == 401:
                    # Mark row as partial and re-raise for outer handler
                    db.update_bruteforce_run(conn, rowid, {
                        "partial": 1,
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    })
                    raise  # caught by outer try/except
                raise

            # Update row with real counters
            db.update_bruteforce_run(conn, rowid, {
                "n_combos": tr["n_combos"],
                "n_validated": tr["n_validated"],
                "n_probed": tr["n_probed"],
                "n_simmed": tr["n_simmed"],
                "n_survivors": tr["n_survivors"],
                "n_additive": tr["n_additive"],
                "quota_hit": int((quota_count + len(tr["additive_alpha_ids"])) >= quota),
                "partial": 0,
                "failure_counts": json.dumps(tr["failure_counts"]),
                "examples": json.dumps(tr["examples"]),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })

            # If _run_template detected a 401 inside bulk-sim, handle clean stop
            if tr.get("hit_401"):
                db.update_bruteforce_run(conn, rowid, {
                    "partial": 1,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                })
                print("[bruteforce] AUTH EXPIRED — 401. Re-run /bruteforce to re-authenticate.")
                print(f"  Templates completed: {n_templates_done}")
                print(f"  Additive survivors found: {quota_count}/{quota}")
                conn.execute(
                    "UPDATE runs SET iterations=?, num_pass=? WHERE run_id=?",
                    (n_simmed_total, quota_count, run_id),
                )
                conn.commit()
                sys.exit(1)

            quota_count += len(tr["additive_alpha_ids"])
            n_simmed_total += tr["n_simmed"]
            additive_ids.extend(tr["additive_alpha_ids"])
            n_templates_done += 1

            if quota_count >= quota:
                stop_reason = "quota_met"
                break
            if max_sims is not None and n_simmed_total >= max_sims:
                stop_reason = "sim_budget"
                break

    except requests.exceptions.HTTPError as e:
        if getattr(getattr(e, "response", None), "status_code", None) == 401:
            # Partial progress already persisted per-template above
            print("[bruteforce] AUTH EXPIRED — 401. Re-run /bruteforce to re-authenticate.")
            print(f"  Templates completed: {n_templates_done}")
            print(f"  Additive survivors found: {quota_count}/{quota}")
            conn.execute(
                "UPDATE runs SET iterations=?, num_pass=? WHERE run_id=?",
                (n_simmed_total, quota_count, run_id),
            )
            conn.commit()
            sys.exit(1)
        raise

    # Loop exhausted without quota_met → stop_reason stays "dry"
    conn.execute(
        "UPDATE runs SET iterations=?, num_pass=? WHERE run_id=?",
        (n_simmed_total, quota_count, run_id),
    )
    conn.commit()

    print(f"[bruteforce] done — stop_reason={stop_reason} quota={quota_count}/{quota}")

    return {
        "quota_count": quota_count,
        "n_templates_done": n_templates_done,
        "stop_reason": stop_reason,
        "additive_ids": additive_ids,
        "sims_used": n_simmed_total,
        "run_id": run_id,
    }


# ---------------------------------------------------------------------------
# __main__ CLI block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from wq_login import login

    parser = argparse.ArgumentParser(description="Brute-force alpha discovery (Tool B)")
    parser.add_argument("--db", default="alpha_kb.db")
    parser.add_argument("--delay", type=int, default=0)
    parser.add_argument("--quota", type=int, default=5)
    parser.add_argument("--probe-size", type=int, default=5)
    parser.add_argument(
        "--templates", nargs="*", default=None,
        help="Template names to run (default: all)",
    )
    args = parser.parse_args()

    client = login()  # ONCE — never inside the loop
    result = bruteforce(
        client,
        db_path=args.db,
        delay=args.delay,
        quota=args.quota,
        probe_size=args.probe_size,
        template_names=args.templates,
    )
    print(f"Stop reason: {result['stop_reason']}")
    print(f"Additive survivors found: {result['quota_count']}/{args.quota}")
    if result["additive_ids"]:
        print(f"Additive alpha_ids: {result['additive_ids']}")
