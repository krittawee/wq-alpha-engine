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
import requests
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
import selfcorr
import validate


# BRAIN concurrency cap: regular accounts allow 3 concurrent simulations,
# Consultant Program members allow 10. Raise to 10 ONLY if your account is a
# Consultant — exceeding the platform cap gets sims rejected/throttled (429).
MAX_CONCURRENT_SIMS = 3


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


def _simulate_to_alpha(client, expression: str, settings: dict = None, attempts: int = 3):
    """Run simulate → wait → get_alpha with retries; return (sim, alpha_dict).

    The vendored SDK's wait() treats "no Retry-After header" as completion, but
    under concurrent load BRAIN can return a non-retry response that is NOT a
    finished alpha (throttle/queue), leaving alpha_id None and making get_alpha()
    raise. Retry a few times with backoff. A 401 propagates immediately — the
    session expired and we never re-authenticate inside the loop.

    settings: optional dict to override _BASE_SETTINGS for this simulation.
    When None, falls back to _BASE_SETTINGS (backward-compatible).
    """
    active_settings = settings if settings is not None else _BASE_SETTINGS
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            sim = client.simulate(expression, settings=active_settings)
            sim.wait(verbose=False)
            if getattr(sim, "alpha_id", None):
                return sim, sim.get_alpha()
            last_err = "wait() returned no alpha_id (transient throttle/queue)"
        except requests.exceptions.HTTPError as e:
            if getattr(getattr(e, "response", None), "status_code", None) == 401:
                raise  # auth expired — abort the whole run, never re-auth
            last_err = str(e)
        except RuntimeError as e:
            last_err = str(e)
        if attempt < attempts:
            time.sleep(5 * attempt)  # linear backoff: 5s, 10s
    raise RuntimeError(
        f"simulation failed after {attempts} attempts: {last_err}"
    )


def grade_one(
    client,
    conn: sqlite3.Connection,
    expression: str,
    run_id: str,
    parent_alpha_id: Optional[str] = None,
    settings: Optional[dict] = None,
) -> dict:
    """Grade a single expression: validate → simulate → IS checks → (if survivor) POST /check → persist.

    Returns a result dict with keys:
        expression, status, alpha_id, is_survivor,
        sharpe, fitness, self_corr, prod_corr, checks.

    parent_alpha_id: when provided, this expression is a mutation of that parent.
        Hook A (proxy_gate) will run before simulation to skip wasteful sims.
        The parent lineage is persisted in the alpha row.

    settings: optional dict to override _BASE_SETTINGS for this simulation.
    When None, falls back to _BASE_SETTINGS (backward-compatible).

    401 from any API call propagates immediately and stops the run.
    """

    # Step 0 — Dedupe check
    # If an existing row is a 'queued' stub (pre-inserted by editor.diagnose_and_mutate),
    # we must NOT skip it — instead inherit its lineage and simulate to replace it.
    existing_id = db.expr_exists(conn, expression)
    stub_id_to_replace: Optional[str] = None
    if existing_id is not None:
        row = conn.execute(
            "SELECT status, parent_alpha_id FROM alphas WHERE alpha_id=?", (existing_id,)
        ).fetchone()
        if row is None or row[0] != "queued":
            print(f"[grade] skip duplicate: {expression[:40]}")
            return {"expression": expression, "status": "duplicate", "alpha_id": existing_id}
        # It's a queued stub — inherit lineage and continue to simulate
        if parent_alpha_id is None:
            parent_alpha_id = row[1]
        stub_id_to_replace = existing_id

    # Step 1 — Local validation
    is_valid, reason = validate.validate(conn, expression)
    if not is_valid:
        print(f"[grade] invalid ({reason}): {expression[:40]}")
        return {"expression": expression, "status": "invalid", "reason": reason}

    # Hook A — proxy-gate: for mutations, check parent PnL similarity before spending
    # a BRAIN sim slot. proxy_gate returns True when parent is too correlated → skip.
    # Graceful degrade: proxy_gate returns False on any error (allows sim to proceed).
    # NOTE: no DB write here — the expression was never simulated so there is no alpha_id.
    if parent_alpha_id is not None:
        if selfcorr.proxy_gate(parent_alpha_id, conn):
            print(f"[grade] proxy-gate filtered (parent {parent_alpha_id}): {expression[:40]}")
            return {"expression": expression, "status": "duplicate", "alpha_id": None}

    # Step 2 — Simulate (Phase A)
    # CRITICAL: call simulate(expression) with expression as the ONLY positional arg.
    # NEVER pass regular= keyword — the SDK silently drops expression if you do.
    print(f"[grade] simulating: {expression[:50]}")
    sim, alpha = _simulate_to_alpha(client, expression, settings=settings)

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

    # Step 5 — Build settings_json (record BRAIN's returned settings; fall back to
    # requested settings if BRAIN response has no settings dict)
    active_settings = settings if settings is not None else _BASE_SETTINGS
    brain_settings = alpha.get("settings") or {}
    # For each persisted field: BRAIN's returned value wins; active_settings is fallback.
    resolved_region        = brain_settings.get("region",         active_settings.get("region"))
    resolved_universe      = brain_settings.get("universe",       active_settings.get("universe"))
    resolved_delay         = brain_settings.get("delay",          active_settings.get("delay"))
    resolved_decay         = brain_settings.get("decay",          active_settings.get("decay"))
    resolved_neutralization= brain_settings.get("neutralization", active_settings.get("neutralization"))
    resolved_truncation    = brain_settings.get("truncation",     active_settings.get("truncation"))
    settings_json = json.dumps({
        "region":         resolved_region,
        "universe":       resolved_universe,
        "delay":          resolved_delay,
        "decay":          resolved_decay,
        "neutralization": resolved_neutralization,
        "truncation":     resolved_truncation,
    })
    status = "pass" if is_survivor else "fail"

    # Step 6 — Persist Phase A results
    now = datetime.utcnow().isoformat()
    alpha_dict = {
        "alpha_id": alpha_id,
        "expression": expression,
        "parent_alpha_id": parent_alpha_id,
        "archetype": None,
        "region": resolved_region,
        "universe": resolved_universe,
        "delay": resolved_delay,
        "decay": resolved_decay,
        "neutralization": resolved_neutralization,
        "truncation": resolved_truncation,
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

    # CR-01: remove queued stub now that the real graded row has been inserted
    if stub_id_to_replace:
        conn.execute("DELETE FROM alphas WHERE alpha_id=?", (stub_id_to_replace,))
        conn.commit()

    # WR-10: guard against empty is.checks — no check data means we can't determine status
    if not checks_raw:
        conn.execute(
            "UPDATE alphas SET status='error' WHERE alpha_id=?", (alpha_id,)
        )
        conn.commit()
        print(f"[grade] WARNING: empty is.checks for {alpha_id} — marked as error")
        return {
            "expression": expression,
            "status": "error",
            "alpha_id": alpha_id,
        }

    print(
        f"[grade] phase A done — alpha_id={alpha_id} "
        f"sharpe={sharpe} survivor={is_survivor}"
    )

    # Phase B — only for IS survivors
    self_corr: Optional[float] = None
    prod_corr: Optional[float] = None
    corr_checked_at: Optional[str] = None

    if is_survivor:
        # Hook B — precise local selfcorr filter (D-08b).
        # Fetch PnL from BRAIN and compare against reference alphas locally.
        # If locally duplicate: mark status='duplicate' in DB, skip BRAIN POST /check.
        # Graceful degrade: if PnL unavailable (fetch returns None), fall through to
        # trigger_correlation_check as before — BRAIN remains the authoritative check.
        pnl_path = selfcorr.fetch_and_cache_pnl(client, alpha_id, conn)
        if pnl_path is not None:
            ref_paths = selfcorr.get_reference_pnl_paths(conn)
            limit_val = selfcorr.get_selfcorr_limit(conn)
            if limit_val is not None and selfcorr.is_duplicate_by_pnl(pnl_path, ref_paths, limit_val):
                conn.execute("UPDATE alphas SET status='duplicate' WHERE alpha_id=?", (alpha_id,))
                conn.commit()
                print(f"[grade] local selfcorr duplicate: {alpha_id}")
                return {
                    "expression": expression,
                    "alpha_id": alpha_id,
                    "status": "duplicate",
                    "is_survivor": is_survivor,
                    "sharpe": sharpe,
                    "fitness": fitness,
                    "self_corr": None,
                    "prod_corr": None,
                    "checks": checks_raw,
                }
        # Only reach trigger_correlation_check if NOT locally duplicate
        try:
            trigger_correlation_check(client, alpha_id)
            corr_checks = poll_correlation(client, alpha_id)
            self_corr = corr_checks.get("SELF_CORRELATION", {}).get("value")
            prod_corr = corr_checks.get("PROD_CORRELATION", {}).get("value")
            corr_checked_at = datetime.utcnow().isoformat()

            # CR-03: Determine final status from SELF_CORRELATION / PROD_CORRELATION result
            # BRAIN is source of truth — never hardcode "pass" here (CLAUDE.md constraint)
            corr_failed = any(c.get("result") == "FAIL" for c in corr_checks.values())
            status_final = "fail" if corr_failed else "pass"

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
    db_path: Optional[str] = None,
    parent_map: Optional[dict] = None,
    settings_map: Optional[dict] = None,
) -> list:
    """Grade a list of expressions. max_workers ≤ MAX_CONCURRENT_SIMS (BRAIN cap).

    expressions may be either:
      - list[str]                      — plain expressions (parent_alpha_id=None)
      - list[tuple[str, str|None]]     — (expression, parent_alpha_id) pairs (WR-01)

    parent_map: optional dict[str, str] mapping expression → parent_alpha_id.
    Overrides tuple-based parent when both are provided.

    settings_map: optional dict[str, dict] mapping expression → settings override.
    When provided, each expression's grade_one call receives the matched settings dict
    instead of _BASE_SETTINGS. Expressions not in settings_map use _BASE_SETTINGS.

    Sequential (max_workers=1) reuses the caller's connection on the main thread.
    For max_workers > 1, each worker opens its OWN SQLite connection — a single
    connection cannot be shared across threads. Pass db_path so workers can open
    the same DB file; falls back to db.DB_PATH.
    """
    # Enforce BRAIN concurrency cap (3 = regular, 10 = Consultant)
    max_workers = min(max_workers, MAX_CONCURRENT_SIMS)

    # WR-01: normalise expressions to (expr, parent_alpha_id) pairs
    pairs: list = []
    for item in expressions:
        if isinstance(item, tuple):
            expr, pid = item[0], item[1] if len(item) > 1 else None
        else:
            expr, pid = item, None
        if parent_map and expr in parent_map:
            pid = parent_map[expr]
        pairs.append((expr, pid))

    results: list = []

    if max_workers <= 1:
        # Sequential — reuses the caller's connection (same thread)
        # WR-06: same failure isolation as the concurrent path — one failure must not
        # abort the entire batch. Re-raise 401 (auth expiry), all others → error result.
        for expr, pid in pairs:
            expr_settings = settings_map.get(expr) if settings_map else None
            try:
                result = grade_one(client, conn, expr, run_id, parent_alpha_id=pid,
                                   settings=expr_settings)
                results.append(result)
            except requests.exceptions.HTTPError as e:
                if getattr(getattr(e, "response", None), "status_code", None) == 401:
                    raise  # auth expired — abort the whole run
                results.append({"expression": expr, "status": "error", "error": str(e)})
            except Exception as e:
                results.append({"expression": expr, "status": "error", "error": str(e)})
    else:
        # Concurrent path: SQLite forbids sharing one connection across threads,
        # so each worker opens its own connection to the same DB file. WAL mode +
        # busy_timeout (set in db.init_db) let concurrent writes serialize safely.
        path = db_path or db.DB_PATH

        def _grade_isolated(pair):
            expr, pid = pair
            expr_settings = settings_map.get(expr) if settings_map else None
            worker_conn = db.init_db(path)
            try:
                return grade_one(client, worker_conn, expr, run_id, parent_alpha_id=pid,
                                 settings=expr_settings)
            except requests.exceptions.HTTPError as e:
                # 401 = auth expired: abort the entire run (never re-auth in-loop).
                if getattr(getattr(e, "response", None), "status_code", None) == 401:
                    raise
                return {"expression": expr, "status": "error", "error": str(e)}
            except Exception as e:
                # One candidate's failure must not kill the whole batch.
                return {"expression": expr, "status": "error", "error": str(e)}
            finally:
                worker_conn.close()

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            # pool.map preserves input order, matching the sequential path.
            results = list(pool.map(_grade_isolated, pairs))

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
        # WR-11: guard against non-numeric Retry-After (HTTP-date format is valid per RFC 7231)
        try:
            retry_after = float(r.headers.get("Retry-After", 0))
        except (TypeError, ValueError):
            retry_after = float(interval)
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
