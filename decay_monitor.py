"""decay_monitor.py — Decay Monitor for OPT-02.

Detects metric degradation in PASS/ACTIVE alphas by comparing consecutive
checks_history rows. Orchestrates re-checks via BRAIN and writes results to
the checks_history time-series table.

Public API:
    detect_decay(conn, alpha_id, threshold_pct) -> dict
    run_decay(client, db_path, threshold_pct) -> dict
"""

import sqlite3
import time
import requests
from datetime import datetime
from typing import Optional

import db
import grade
from brain_client import BASE_URL

# Default degradation threshold: 15%.
# Rationale: BRAIN metrics fluctuate ~5% from market data updates alone.
# 15% signals real degradation (not noise) while still catching gradual slides
# (not only PASS→FAIL crossings). Configurable via --threshold in decay.py.
DEFAULT_DECAY_THRESHOLD = 0.15


def detect_decay(
    conn: sqlite3.Connection,
    alpha_id: str,
    threshold_pct: float = DEFAULT_DECAY_THRESHOLD,
) -> dict:
    """Compare the latest two checks_history rows for alpha_id.

    Queries checks_history for the two most recent rows per key metric
    (LOW_SHARPE, LOW_FITNESS) ordered by checked_at DESC. Computes:
        drop_pct = (old_val - new_val) / abs(old_val)
    A drop_pct > threshold_pct is flagged as 'degraded'.

    Returns:
        {"status": "degraded", "metric": ..., "old_value": ..., "new_value": ...,
         "drop_pct": ..., "checked_at": ...}
        {"status": "stable",   "metric": None}
        {"status": "no_data",  "metric": None}   # no metric has ≥2 rows

    Semantics for no_data:
    - If the alpha has no checks_history rows at all, return no_data immediately.
    - If at least one metric has ≥2 rows, it can be evaluated (stable/degraded).
    - A metric with <2 rows is skipped (insufficient data for that metric only).
    - no_data is only returned when ALL metrics are skipped due to insufficient data.

    Security: all SQL uses ? parameterized queries (T-04-14).
    """
    # Check for any rows at all — if completely empty, return no_data immediately.
    total_rows = conn.execute(
        "SELECT COUNT(*) FROM checks_history WHERE alpha_id=?",
        (alpha_id,),
    ).fetchone()[0]
    if total_rows < 2:
        return {"status": "no_data", "metric": None}

    any_evaluated = False

    for metric_check in ("LOW_SHARPE", "LOW_FITNESS"):
        rows = conn.execute(
            "SELECT value, checked_at FROM checks_history "
            "WHERE alpha_id=? AND name=? "
            "ORDER BY checked_at DESC LIMIT 2",
            (alpha_id, metric_check),
        ).fetchall()

        if len(rows) < 2:
            # Not enough data for this specific metric — skip it (not a global no_data).
            continue

        any_evaluated = True
        new_val, new_at = rows[0]
        old_val, _ = rows[1]

        if new_val is None or old_val is None:
            continue  # Missing values — skip this metric

        if abs(old_val) < 1e-6:
            continue  # Avoid division by zero for near-zero old values

        drop_pct = (old_val - new_val) / abs(old_val)

        if drop_pct > threshold_pct:
            return {
                "status": "degraded",
                "metric": metric_check,
                "old_value": old_val,
                "new_value": new_val,
                "drop_pct": drop_pct,
                "checked_at": new_at,
            }

    if not any_evaluated:
        return {"status": "no_data", "metric": None}

    return {"status": "stable", "metric": None}


def run_decay(
    client,
    db_path: str = "alpha_kb.db",
    threshold_pct: float = DEFAULT_DECAY_THRESHOLD,
) -> dict:
    """Re-check all PASS+ACTIVE alphas and flag metric degradation.

    Orchestration flow per alpha:
      1. GET /alphas/{alpha_id} for fresh IS stats (sharpe, fitness).
      2. Trigger correlation re-check via grade.trigger_correlation_check.
      3. Poll for results via grade.poll_correlation.
      4. Build checks_list combining corr checks + IS metric synthetic entries.
      5. Append to checks_history (append-only — never overwrite).
      6. Call detect_decay to compare latest two rows.

    Scope: status IN ('pass', 'ACTIVE') only.
    NOT 'UNSUBMITTED' (363 pre-Phase-2 alphas with different status vocabulary).

    401 handling (CLAUDE.md): a 401 from BRAIN propagates immediately and
    stops the run. Rows already appended before the 401 are preserved (partial
    run is valid per Pitfall 4). Never re-auth in-loop.

    TimeoutError from poll_correlation: logged as warning, loop continues.

    Returns:
        {
            "checked": N,
            "degraded": M,
            "degraded_alphas": [{"alpha_id": ..., "decay_status": {...}}, ...]
        }
    """
    conn = db.init_db(db_path)
    run_tag = "decay_" + datetime.utcnow().strftime("%Y-%m-%d")

    # Query PASS+ACTIVE alphas only (not UNSUBMITTED — different status vocabulary).
    alpha_rows = conn.execute(
        "SELECT alpha_id FROM alphas WHERE status IN ('pass', 'ACTIVE')"
    ).fetchall()

    results = []

    for (alpha_id,) in alpha_rows:
        # --- Step 1: GET /alphas/{alpha_id} for fresh IS stats ---
        # Use client._session.get (authenticated session) not bare requests.get.
        # Mirrors grade.py line 446/474 pattern exactly.
        sharpe = None
        fitness = None
        try:
            resp = client._session.get(f"{BASE_URL}/alphas/{alpha_id}")
            resp.raise_for_status()
            alpha_data = resp.json()
            is_data = alpha_data.get("is", {})
            sharpe = is_data.get("sharpe")
            fitness = is_data.get("fitness")
        except requests.exceptions.HTTPError as e:
            if getattr(getattr(e, "response", None), "status_code", None) == 401:
                print(
                    f"[decay] Session expired at alpha {alpha_id} — "
                    "re-run /decay to continue."
                )
                raise  # propagate 401 — stop the run; partial rows are preserved
            print(f"[decay] Warning: GET /alphas/{alpha_id} failed: {e}")

        # --- Steps 2+3: Trigger and poll correlation re-check ---
        corr_checks = {}
        try:
            grade.trigger_correlation_check(client, alpha_id)
            corr_checks = grade.poll_correlation(client, alpha_id)
        except TimeoutError as e:
            print(f"[decay] Warning: correlation poll timed out for {alpha_id}: {e}")
        except requests.exceptions.HTTPError as e:
            if getattr(getattr(e, "response", None), "status_code", None) == 401:
                print(
                    f"[decay] Session expired at alpha {alpha_id} — "
                    "re-run /decay to continue."
                )
                raise
            print(f"[decay] Warning: correlation check failed for {alpha_id}: {e}")

        # --- Step 4: Build checks_list ---
        # Start from correlation check results.
        checks_list = list(corr_checks.values()) if corr_checks else []

        # Add IS metric synthetic entries if we got fresh IS stats.
        # Read limit from existing checks table (never hardcode per CLAUDE.md).
        if sharpe is not None:
            sharpe_limit_row = conn.execute(
                "SELECT limit_val FROM checks WHERE alpha_id=? AND name='LOW_SHARPE'",
                (alpha_id,),
            ).fetchone()
            sharpe_limit = sharpe_limit_row[0] if sharpe_limit_row else None
            checks_list.append({
                "name": "LOW_SHARPE",
                "result": "PASS" if (sharpe_limit is None or sharpe >= sharpe_limit) else "FAIL",
                "value": sharpe,
                "limit": sharpe_limit,
            })

        if fitness is not None:
            fitness_limit_row = conn.execute(
                "SELECT limit_val FROM checks WHERE alpha_id=? AND name='LOW_FITNESS'",
                (alpha_id,),
            ).fetchone()
            fitness_limit = fitness_limit_row[0] if fitness_limit_row else None
            checks_list.append({
                "name": "LOW_FITNESS",
                "result": "PASS" if (fitness_limit is None or fitness >= fitness_limit) else "FAIL",
                "value": fitness,
                "limit": fitness_limit,
            })

        # --- Step 5: Append to checks_history (append-only) ---
        if checks_list:
            db.append_checks_history(conn, alpha_id, checks_list, run_tag=run_tag)

        # --- Step 6: Detect decay ---
        decay_status = detect_decay(conn, alpha_id, threshold_pct=threshold_pct)
        results.append({"alpha_id": alpha_id, "decay_status": decay_status})

    # Filter degraded alphas
    degraded = [r for r in results if r["decay_status"]["status"] == "degraded"]

    # Print CLI table
    if degraded:
        print(f"\n[decay] Degraded alphas ({len(degraded)}):")
        print(f"  {'Alpha ID':<20} {'Metric':<20} {'Old':>8} {'New':>8} {'Drop%':>8}")
        print(f"  {'-'*20} {'-'*20} {'-'*8} {'-'*8} {'-'*8}")
        for r in degraded:
            ds = r["decay_status"]
            drop_str = f"{ds['drop_pct'] * 100:.1f}%"
            print(
                f"  {r['alpha_id']:<20} {ds['metric']:<20} "
                f"{ds['old_value']:>8.4f} {ds['new_value']:>8.4f} {drop_str:>8}"
            )
    else:
        print("[decay] No degradation detected.")

    # Write Obsidian decay note if obsidian module is available (D-07)
    try:
        import obsidian  # type: ignore
        obsidian.write_decay_note(degraded, conn)
    except ImportError:
        pass  # obsidian module not yet available — skip note writing

    checked_count = len(alpha_rows)
    return {
        "checked": checked_count,
        "degraded": len(degraded),
        "degraded_alphas": degraded,
    }
