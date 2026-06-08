"""grade.py — Two-phase grader for WorldQuant BRAIN alpha expressions.

Phase A: validate → simulate → read IS checks dynamically from BRAIN.
Phase B (IS survivors only): POST /alphas/{id}/check → poll until
         SELF_CORRELATION / PROD_CORRELATION leave PENDING → persist.

Public API:
    grade_one(client, conn, expression, run_id) -> dict
    grade_many(client, conn, expressions, run_id, max_workers=1) -> list[dict]
    trigger_correlation_check(client, alpha_id) -> None
    poll_correlation(client, alpha_id, timeout=300, interval=15) -> dict
"""

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

__all__ = [
    "grade_one",
    "grade_many",
    "trigger_correlation_check",
    "poll_correlation",
]

from brain_client import BASE_URL
import db
import validate


# Default simulation settings (from PATTERNS.md / brain_client.py defaults).
# These match the SDK defaults so client.simulate(expr) uses them automatically.
# Stored per-alpha in settings_json for record-keeping.
_BASE_SETTINGS = {
    "instrumentType": "EQUITY",
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 15,
    "neutralization": "SUBINDUSTRY",
    "truncation": 0.08,
    "maxTrade": "ON",
    "pasteurization": "ON",
    "testPeriod": "P1Y6M",
    "unitHandling": "VERIFY",
    "nanHandling": "OFF",
    "language": "FASTEXPR",
    "visualization": False,
}


def grade_one(
    client,
    conn: sqlite3.Connection,
    expression: str,
    run_id: str,
) -> dict:
    """Grade a single expression: validate → simulate → IS checks → (if survivor) POST /check → persist.

    Returns a result dict with keys:
        expression, status, alpha_id, is_survivor,
        sharpe, fitness, self_corr, prod_corr, checks.

    401 from any API call propagates immediately and stops the run.
    """

    # Step 0 — Dedupe check
    existing_id = db.expr_exists(conn, expression)
    if existing_id is not None:
        print(f"[grade] skip duplicate: {expression[:40]}")
        return {"expression": expression, "status": "duplicate", "alpha_id": existing_id}

    # Step 1 — Local validation
    is_valid, reason = validate.validate(conn, expression)
    if not is_valid:
        print(f"[grade] invalid ({reason}): {expression[:40]}")
        return {"expression": expression, "status": "invalid", "reason": reason}

    # Step 2 — Simulate (Phase A)
    # CRITICAL: call simulate(expression) with expression as the ONLY positional arg.
    # NEVER pass regular= keyword — the SDK silently drops expression if you do.
    print(f"[grade] simulating: {expression[:50]}")
    sim = client.simulate(expression)
    sim.wait(verbose=False)
    alpha = sim.get_alpha()

    # Extract alpha_id — try sim attribute first, then alpha dict.
    alpha_id: Optional[str] = getattr(sim, "alpha_id", None)
    if not alpha_id:
        alpha_id = alpha.get("id") or alpha.get("alpha_id", "")

    # Step 3 — Extract IS stats from the alpha dict
    is_data = alpha.get("is", {})
    sharpe = is_data.get("sharpe")
    fitness = is_data.get("fitness")
    turnover = is_data.get("turnover")
    returns = is_data.get("returns")
    drawdown = is_data.get("drawdown")
    margin = is_data.get("margin")
    long_count = is_data.get("longCount") or is_data.get("long_count")
    short_count = is_data.get("shortCount") or is_data.get("short_count")

    # Step 4 — Extract IS checks dynamically from BRAIN's is.checks array.
    # BRAIN is source of truth; never hardcode limits or thresholds.
    checks_raw = is_data.get("checks", [])

    # is_survivor = True when no IS check has result=="FAIL"
    # (PENDING is expected for SELF_CORRELATION / PROD_CORRELATION at this stage).
    is_survivor = all(
        c.get("result") != "FAIL"
        for c in checks_raw
        if c.get("result") != "PENDING"
    )

    # Step 5 — Build settings_json (record the defaults used for this alpha)
    settings_json = json.dumps(_BASE_SETTINGS)
    status = "pass" if is_survivor else "fail"

    # Step 6 — Persist Phase A results
    now = datetime.utcnow().isoformat()
    alpha_dict = {
        "alpha_id": alpha_id,
        "expression": expression,
        "parent_alpha_id": None,
        "archetype": None,
        "region": _BASE_SETTINGS["region"],
        "universe": _BASE_SETTINGS["universe"],
        "delay": _BASE_SETTINGS["delay"],
        "decay": _BASE_SETTINGS["decay"],
        "neutralization": _BASE_SETTINGS["neutralization"],
        "truncation": _BASE_SETTINGS["truncation"],
        "settings_json": settings_json,
        "sharpe": sharpe,
        "fitness": fitness,
        "turnover": turnover,
        "returns": returns,
        "drawdown": drawdown,
        "margin": margin,
        "long_count": long_count,
        "short_count": short_count,
        # Phase B fills these; None for now
        "self_corr": None,
        "prod_corr": None,
        "corr_checked_at": None,
        "pnl_path": None,
        "status": status,
        "run_id": run_id,
        "created_at": now,
    }
    db.upsert_alpha(conn, alpha_dict)
    db.upsert_checks(conn, alpha_id, checks_raw)

    print(
        f"[grade] phase A done — alpha_id={alpha_id} "
        f"sharpe={sharpe} survivor={is_survivor}"
    )

    # Phase B — only for IS survivors
    self_corr: Optional[float] = None
    prod_corr: Optional[float] = None
    corr_checked_at: Optional[str] = None

    if is_survivor:
        try:
            trigger_correlation_check(client, alpha_id)
            corr_checks = poll_correlation(client, alpha_id)
            self_corr = corr_checks.get("SELF_CORRELATION", {}).get("value")
            prod_corr = corr_checks.get("PROD_CORRELATION", {}).get("value")
            corr_checked_at = datetime.utcnow().isoformat()

            # Determine final status after correlation results
            status_final = "pass"

            # Write correlation values back to alphas row
            conn.execute(
                "UPDATE alphas SET self_corr=?, prod_corr=?, corr_checked_at=?, status=? "
                "WHERE alpha_id=?",
                (self_corr, prod_corr, corr_checked_at, status_final, alpha_id),
            )
            conn.commit()

            # Persist correlation check records
            db.upsert_checks(conn, alpha_id, list(corr_checks.values()))

            print(
                f"[grade] phase B done — self_corr={self_corr} prod_corr={prod_corr}"
            )
            status = status_final

        except TimeoutError as exc:
            print(f"[grade] WARNING: correlation check timed out — {exc}")
            # Leave self_corr/prod_corr as None; mark status as timeout
            conn.execute(
                "UPDATE alphas SET status=? WHERE alpha_id=?",
                ("timeout", alpha_id),
            )
            conn.commit()
            status = "timeout"

    return {
        "expression": expression,
        "alpha_id": alpha_id,
        "status": status,
        "is_survivor": is_survivor,
        "sharpe": sharpe,
        "fitness": fitness,
        "self_corr": self_corr,
        "prod_corr": prod_corr,
        "checks": checks_raw,
    }


def grade_many(
    client,
    conn: sqlite3.Connection,
    expressions: list,
    run_id: str,
    max_workers: int = 1,
) -> list:
    """Grade a list of expressions. max_workers ≤ 3 (BRAIN concurrency cap).

    Phase 1 default is max_workers=1 (sequential).
    ThreadPoolExecutor is used when max_workers > 1 (future path).
    """
    # Enforce BRAIN concurrency cap
    max_workers = min(max_workers, 3)

    results: list = []

    if max_workers <= 1:
        # Sequential — Phase 1 default
        for expr in expressions:
            result = grade_one(client, conn, expr, run_id)
            results.append(result)
    else:
        # Concurrent path (future Phase 2+)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(grade_one, client, conn, expr, run_id)
                for expr in expressions
            ]
            for future in futures:
                results.append(future.result())

    # Summary table
    print("\n[grade] Summary:")
    print(f"  {'Expression':<52} {'Status':<10} {'Sharpe'}")
    print(f"  {'-'*52} {'-'*10} {'-'*8}")
    for r in results:
        expr_display = r.get("expression", "")[:50]
        status_display = r.get("status", "")
        sharpe_display = r.get("sharpe")
        sharpe_str = f"{sharpe_display:.4f}" if sharpe_display is not None else "N/A"
        print(f"  {expr_display:<52} {status_display:<10} {sharpe_str}")

    return results


# ---------------------------------------------------------------------------
# Phase B helpers
# ---------------------------------------------------------------------------


def trigger_correlation_check(client, alpha_id: str) -> None:
    """Kick off the submission/correlation check via GET /alphas/{alpha_id}/check.

    BRAIN computes correlation as part of the submission check, served from the
    GET /alphas/{id}/check endpoint using an async Retry-After pattern. POST is
    NOT allowed there (returns 405: Allow = GET, PUT, PATCH, HEAD, OPTIONS).
    This first GET initiates computation; poll_correlation drives it to
    completion. Uses client._session; a 401 propagates immediately.
    """
    r = client._session.get(f"{BASE_URL}/alphas/{alpha_id}/check")
    r.raise_for_status()
    print(f"[grade] kicked off /check for {alpha_id}")


def poll_correlation(
    client,
    alpha_id: str,
    timeout: int = 300,
    interval: int = 15,
) -> dict:
    """Poll GET /alphas/{alpha_id}/check until correlation checks leave PENDING.

    The submission-check endpoint returns {"is": {"checks": [...]}} with
    SELF_CORRELATION (and PROD_CORRELATION when the account has permission),
    using a Retry-After async pattern while computing.

    Returns whichever of {SELF_CORRELATION, PROD_CORRELATION} are present and
    resolved. PROD_CORRELATION is commonly absent (requires a permission many
    accounts lack — the dedicated /correlations/prod endpoint returns 403), so
    callers must treat a missing prod value as None rather than an error.
    Raises TimeoutError if not resolved within timeout seconds.

    401 propagates via raise_for_status() — no re-auth.
    """
    deadline = time.time() + timeout

    while time.time() < deadline:
        r = client._session.get(f"{BASE_URL}/alphas/{alpha_id}/check")

        # Check Retry-After header first (canonical polling pattern from brain_client.py)
        retry_after = float(r.headers.get("Retry-After", 0))
        if retry_after > 0:
            time.sleep(retry_after)
            continue

        # No Retry-After — response should be final
        r.raise_for_status()
        alpha = r.json()
        checks = alpha.get("is", {}).get("checks", [])

        corr_checks = {
            c["name"]: c
            for c in checks
            if c["name"] in ("SELF_CORRELATION", "PROD_CORRELATION")
        }

        pending = [
            name
            for name, c in corr_checks.items()
            if c.get("result") == "PENDING"
        ]

        if not pending:
            return corr_checks

        time.sleep(interval)

    raise TimeoutError(
        f"Correlation check timed out after {timeout}s for alpha {alpha_id}"
    )
