"""sync.py — Pull BRAIN's operator catalog, paginated data-fields catalog,
and the user's existing alphas into alpha_kb.db.

Usage:
    python sync.py            # standalone refresh

All HTTP calls use client._session (a requests.Session) authenticated via
wq_login.py. Never re-authenticates inside sync functions — a 401 propagates
immediately via raise_for_status() to stop the run.
"""

import json
import sqlite3
import sys
import time
from typing import Optional

from brain_client import BASE_URL
import db


# BRAIN rate-limits rapid request bursts with HTTP 429. We pause briefly between
# paginated pages and, on a 429, honor the Retry-After header and back off rather
# than crashing the sync.
_PAGE_DELAY = 0.5      # seconds between successive pages
_MAX_RETRIES = 6


def _get(session, url, params=None):
    """GET with 429 handling: honor Retry-After and retry; raise on other errors.

    A 401 still propagates immediately via raise_for_status() (never re-auth in loop).
    """
    for attempt in range(_MAX_RETRIES):
        r = session.get(url, params=params)
        if r.status_code == 429:
            retry_after = float(r.headers.get("Retry-After", 5))
            print(f"[sync] rate-limited (429) — waiting {retry_after:.0f}s "
                  f"(attempt {attempt + 1}/{_MAX_RETRIES})...")
            time.sleep(retry_after)
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()  # retries exhausted — surface the last 429
    return r


def sync_operators(client, conn: sqlite3.Connection) -> int:
    """Fetch GET /operators, upsert into operators table. Returns count.

    A 401 response raises via raise_for_status() and stops the run immediately.
    Never catches HTTPError — auth errors must surface.
    """
    r = _get(client._session, f"{BASE_URL}/operators")
    data = r.json()

    # BRAIN may return {"results": [...]} or a plain list.
    if isinstance(data, list):
        raw = data
    else:
        raw = data.get("results", [])

    rows = [
        {
            "name": op.get("name", ""),
            "category": op.get("category", ""),
            "definition": op.get("definition", ""),
            "signature": op.get("signature", ""),
        }
        for op in raw
    ]
    db.upsert_operators(conn, rows)
    print(f"[sync] operators: {len(rows)} rows")
    return len(rows)


def sync_datafields(
    client,
    conn: sqlite3.Connection,
    dataset_id: Optional[str] = None,
    region: str = "USA",
    universe: str = "TOP3000",
    delay: int = 1,
    instrument_type: str = "EQUITY",
) -> int:
    """Page through GET /data-fields, upsert all rows. Returns total count.

    dataset_id=None (default) syncs the FULL field namespace for the given
    region/universe/delay (~8k fields) so the local validator mirrors everything
    BRAIN accepts — no false "unknown field" rejections. Pass a dataset id
    (e.g. "fundamental6") to sync a single dataset instead.

    Uses offset/limit pagination (limit=50 per page — BRAIN's /data-fields
    rejects larger pages with "pagination limit too high"). instrumentType=EQUITY
    is required; omitting it returns 400 ["Invalid query"]. A 401 propagates
    immediately.
    """
    params = {
        "instrumentType": instrument_type,
        "region": region,
        "delay": delay,
        "universe": universe,
        "limit": 50,
        "offset": 0,
    }
    if dataset_id is not None:
        params["dataset.id"] = dataset_id
    total = 0
    while True:
        r = _get(client._session, f"{BASE_URL}/data-fields", params)
        page = r.json()

        # BRAIN returns {"results": [...], "count": N} or similar.
        if isinstance(page, list):
            results = page
        else:
            results = page.get("results", [])

        if not results:
            break

        batch = [
            {
                "id": f.get("id", ""),
                "description": f.get("description", ""),
                "dataset": f.get("dataset", {}).get("id", dataset_id)
                           if isinstance(f.get("dataset"), dict)
                           else f.get("dataset", dataset_id),
                "region": f.get("region", region),
                "universe": f.get("universe", universe),
                "delay": f.get("delay", delay),
                "type": f.get("type", ""),
            }
            for f in results
        ]
        db.upsert_datafields(conn, batch)
        total += len(results)
        params["offset"] += len(results)
        time.sleep(_PAGE_DELAY)  # be polite to the rate limiter

    print(f"[sync] datafields: total {total} rows")
    return total


def sync_existing_alphas(client, conn: sqlite3.Connection) -> int:
    """Page through GET /users/self/alphas, upsert each into alphas table. Returns count.

    Seeds the self-correlation memory with the user's existing BRAIN alphas.
    BRAIN has no bare GET /alphas list endpoint (that returns 405) — the user's
    own alphas live under the user-scoped /users/self/alphas path.
    Pagination uses offset/limit (limit=100). A 401 propagates immediately.
    """
    params = {"limit": 100, "offset": 0}
    total = 0

    while True:
        r = _get(client._session, f"{BASE_URL}/users/self/alphas", params)
        page = r.json()

        if isinstance(page, list):
            results = page
        else:
            results = page.get("results", [])

        if not results:
            break

        for alpha in results:
            settings = alpha.get("settings") or {}

            # Extract IS stats from alpha["is"] if present.
            is_data = alpha.get("is") or {}
            sharpe = is_data.get("sharpe")
            fitness = is_data.get("fitness")
            turnover = is_data.get("turnover")
            returns = is_data.get("returns")

            # BRAIN returns `regular` as a dict {code, description, operatorCount}
            # for regular alphas — the expression string is under "code".
            regular = alpha.get("regular")
            if isinstance(regular, dict):
                expression = regular.get("code", "")
            else:
                expression = regular or alpha.get("expression", "")

            alpha_dict = {
                "alpha_id": alpha.get("id") or alpha.get("alpha_id", ""),
                "expression": expression,
                "parent_alpha_id": None,
                "archetype": None,
                "region": settings.get("region", alpha.get("region", "")),
                "universe": settings.get("universe", alpha.get("universe", "")),
                "delay": settings.get("delay", alpha.get("delay")),
                "decay": settings.get("decay", alpha.get("decay")),
                "neutralization": settings.get("neutralization", alpha.get("neutralization")),
                "truncation": settings.get("truncation", alpha.get("truncation")),
                "settings_json": json.dumps(settings),
                "sharpe": sharpe,
                "fitness": fitness,
                "turnover": turnover,
                "returns": returns,
                "drawdown": is_data.get("drawdown"),
                "margin": is_data.get("margin"),
                "long_count": is_data.get("longCount") or is_data.get("long_count"),
                "short_count": is_data.get("shortCount") or is_data.get("short_count"),
                "self_corr": None,
                "prod_corr": None,
                "corr_checked_at": None,
                "pnl_path": None,
                "status": alpha.get("status", ""),
                "run_id": None,
                "created_at": alpha.get("dateCreated") or alpha.get("created_at", ""),
            }
            db.upsert_alpha(conn, alpha_dict)
            total += 1

        params["offset"] += len(results)
        time.sleep(_PAGE_DELAY)  # be polite to the rate limiter

    print(f"[sync] existing alphas: {total} synced")
    return total


def sync_all(client, conn: sqlite3.Connection) -> None:
    """Run sync_operators, sync_datafields, sync_existing_alphas in order."""
    sync_operators(client, conn)
    sync_datafields(client, conn)
    sync_existing_alphas(client, conn)
    print("[sync] complete")


if __name__ == "__main__":
    from wq_login import login

    client = login()
    conn = db.init_db()
    sync_all(client, conn)
    conn.close()
