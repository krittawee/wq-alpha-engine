"""selfcorr.py — Local PnL-based self-correlation pre-filter.

Two-stage filter (D-08):
  (a) proxy_gate: pre-sim check using parent's already-cached PnL.
  (b) precise_filter: post-sim check on candidate's own PnL before
      triggering BRAIN's POST /check.

Uses Python stdlib only (no numpy). Gracefully degrades to None/False when
PnL is unavailable — never blocks grading (D-13).

Auth constraint (CLAUDE.md): 401 from get_pnl() always propagates immediately.
Never re-authenticate inside the loop.
Concurrency constraint: backfill_active_pnl is sequential I/O — do NOT call
it inside the ≤3-concurrent sim pool.
"""

import json
import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

# Module-level constant for default PnL cache directory (relative to project root)
PNL_CACHE_DIR = Path("pnl_cache")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _filter_to_recent(
    pnls: list, dates: list, years: int = 2
) -> tuple:
    """Filter pnls/dates to the most recent `years` years.

    Args:
        pnls: cumulative PnL series
        dates: ISO date strings aligned 1:1 with pnls
        years: number of years to keep (default 2)

    Returns:
        (filtered_pnls, filtered_dates). Returns (pnls, dates) unchanged
        if dates is empty or malformed.
    """
    if not dates:
        return pnls, dates

    try:
        parsed = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
    except (ValueError, TypeError):
        return pnls, dates

    if not parsed:
        return pnls, dates

    cutoff = max(parsed) - timedelta(days=365 * years)
    filtered = [
        (p, d) for p, d in zip(pnls, parsed) if d >= cutoff
    ]
    if not filtered:
        return pnls, dates

    fp, fd = zip(*filtered)
    return list(fp), [d.strftime("%Y-%m-%d") for d in fd]


def _pnls_to_daily_returns(pnls: list) -> list:
    """Convert cumulative PnL series to daily returns.

    Forward-fills None/NaN values, then computes:
        returns[i] = pnls[i] - pnls[i-1]  for i in 1..len(pnls)

    Args:
        pnls: list of floats (cumulative PnL, may contain None)

    Returns:
        list of len(pnls)-1 floats representing daily returns
    """
    if len(pnls) < 2:
        return []

    # Forward-fill None/NaN
    filled = []
    last_valid = 0.0
    for v in pnls:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            filled.append(last_valid)
        else:
            last_valid = float(v)
            filled.append(last_valid)

    return [filled[i] - filled[i - 1] for i in range(1, len(filled))]


def _pearson(x: list, y: list) -> float:
    """Pearson correlation of two float lists using stdlib math only.

    Returns 0.0 if:
      - fewer than 2 data points after length alignment
      - either series has zero standard deviation

    Aligns by min length: n = min(len(x), len(y)).
    Callers should align date-overlapping vectors before calling this;
    shorter vectors from date alignment are handled naturally.
    """
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    x = x[:n]
    y = y[:n]
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if sx == 0.0 or sy == 0.0:
        return 0.0
    return num / (sx * sy)


def _date_overlap_returns(
    path_a: str, path_b: str
) -> tuple:
    """Load two PnL JSONs and return daily returns aligned to their date overlap.

    Finds the overlapping date set between both PnL files and aligns both
    cumulative PnL vectors to those dates before converting to daily returns.

    Args:
        path_a: path to first PnL JSON file
        path_b: path to second PnL JSON file

    Returns:
        (returns_a, returns_b) for the overlapping period.
        Returns ([], []) if overlap < 60 trading days (graceful degrade D-13).
        Returns ([], []) on any read/parse error.
    """
    try:
        data_a = json.loads(Path(path_a).read_text())
        data_b = json.loads(Path(path_b).read_text())
    except Exception:
        return [], []

    dates_a = data_a.get("dates", [])
    pnls_a = data_a.get("pnls", [])
    dates_b = data_b.get("dates", [])
    pnls_b = data_b.get("pnls", [])

    if not dates_a or not dates_b or len(dates_a) != len(pnls_a) or len(dates_b) != len(pnls_b):
        return [], []

    # Build date-to-pnl maps
    map_a = {d: p for d, p in zip(dates_a, pnls_a)}
    map_b = {d: p for d, p in zip(dates_b, pnls_b)}

    # Overlapping dates sorted
    overlap = sorted(set(map_a.keys()) & set(map_b.keys()))

    if len(overlap) < 60:
        # Less than 60 trading days overlap → skip comparison (graceful degrade D-13)
        return [], []

    aligned_a = [map_a[d] for d in overlap]
    aligned_b = [map_b[d] for d in overlap]

    return _pnls_to_daily_returns(aligned_a), _pnls_to_daily_returns(aligned_b)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_and_cache_pnl(
    client,
    alpha_id: str,
    conn: sqlite3.Connection,
    pnl_dir: str = "pnl_cache",
) -> Optional[str]:
    """Fetch PnL from BRAIN, cache to JSON, update pnl_path in DB.

    Auth constraint (CLAUDE.md): 401 always propagates — never caught-and-retried.
    Graceful degrade (D-13): all other errors return None.

    Args:
        client: BRAIN client with get_pnl(alpha_id) method
        alpha_id: BRAIN alpha ID to fetch PnL for
        conn: SQLite connection (updates alphas.pnl_path)
        pnl_dir: directory for PnL JSON cache files (default: "pnl_cache")

    Returns:
        str path to cached JSON file, or None on any non-401 failure
    """
    try:
        pnl_data = client.get_pnl(alpha_id)
    except requests.exceptions.HTTPError as e:
        if getattr(getattr(e, "response", None), "status_code", None) == 401:
            raise  # auth expiry — always propagate (CLAUDE.md constraint)
        return None  # other HTTP error → graceful degrade (D-13)
    except Exception:
        return None  # timeout / malformed → graceful degrade (D-13)

    pnls = pnl_data.get("pnls", [])
    dates = pnl_data.get("dates", [])
    # Log actual keys on first fetch to help catch schema mismatch (A1 mitigation)
    print(f"[selfcorr] fetch_and_cache_pnl({alpha_id}): keys={list(pnl_data.keys())}, "
          f"pnls={len(pnls)}, dates={len(dates)}")

    path = Path(pnl_dir) / f"{alpha_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pnls": pnls, "dates": dates}))

    conn.execute(
        "UPDATE alphas SET pnl_path=? WHERE alpha_id=?",
        (str(path), alpha_id),
    )
    conn.commit()
    return str(path)


def load_returns(pnl_path: str) -> list:
    """Load PnL JSON, filter to last 2 years, return daily returns.

    Args:
        pnl_path: path to cached PnL JSON file

    Returns:
        list of floats (daily returns). Returns [] on any read/parse error.
    """
    try:
        data = json.loads(Path(pnl_path).read_text())
        pnls = data.get("pnls", [])
        dates = data.get("dates", [])
    except Exception:
        return []

    filtered_pnls, _ = _filter_to_recent(pnls, dates, years=2)
    return _pnls_to_daily_returns(filtered_pnls)


def get_reference_pnl_paths(conn: sqlite3.Connection) -> list:
    """Return pnl_path for all PASS alphas + ACTIVE (submitted) alphas with cached PnL.

    Reference set per D-09: submitted (ACTIVE) alphas mirror BRAIN's real self-corr;
    PASS alphas stop the autonomous loop from rediscovering itself.

    Args:
        conn: SQLite connection

    Returns:
        list of pnl_path strings
    """
    rows = conn.execute(
        "SELECT pnl_path FROM alphas"
        " WHERE pnl_path IS NOT NULL AND status IN ('pass', 'ACTIVE')"
    ).fetchall()
    return [row[0] for row in rows]


def get_selfcorr_limit(conn: sqlite3.Connection) -> Optional[float]:
    """Read SELF_CORRELATION limit_val from checks table at runtime.

    NEVER hardcode 0.7 — this must read from DB (D-11, CLAUDE.md).

    Args:
        conn: SQLite connection

    Returns:
        float limit_val from checks table, or None if no resolved row exists
    """
    row = conn.execute(
        "SELECT limit_val FROM checks"
        " WHERE name='SELF_CORRELATION' AND limit_val IS NOT NULL LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def max_pearson(candidate_path: str, reference_paths: list) -> float:
    """Compute max Pearson correlation between candidate and all reference alphas.

    Uses date-overlap aligned daily returns (D-10). Gracefully skips references
    with insufficient overlap (D-13).

    Args:
        candidate_path: path to candidate PnL JSON
        reference_paths: list of reference PnL JSON paths

    Returns:
        max Pearson correlation (0.0 if no valid comparisons)
    """
    max_corr = 0.0
    for ref_path in reference_paths:
        cand_r, ref_r = _date_overlap_returns(candidate_path, ref_path)
        if len(cand_r) < 2:
            continue  # skip this reference (graceful degrade D-13)
        corr = _pearson(cand_r, ref_r)
        if corr > max_corr:
            max_corr = corr
    return max_corr


def is_duplicate_by_pnl(
    candidate_path: str,
    reference_paths: list,
    limit_val: float,
    margin: float = 0.0,
) -> bool:
    """Return True if candidate is too similar to any reference alpha (D-08b precise filter).

    Args:
        candidate_path: path to candidate PnL JSON
        reference_paths: list of reference PnL JSON paths
        limit_val: SELF_CORRELATION limit from checks table (read via get_selfcorr_limit)
        margin: optional safety margin (default 0.0)

    Returns:
        True if max_pearson(candidate, references) >= limit_val - margin
    """
    return max_pearson(candidate_path, reference_paths) >= (limit_val - margin)


def proxy_gate(parent_alpha_id: str, conn: sqlite3.Connection) -> bool:
    """Pre-sim proxy gate (D-08a): check parent's cached PnL against reference set.

    If parent is too correlated to the reference set, skip simulating the mutation.
    This avoids wasting BRAIN API calls on clearly-duplicate lineages.

    Graceful degrade (D-13): returns False (allow sim to proceed) on ANY failure —
    missing PnL path, no limit in DB, empty reference set, or any exception.

    Args:
        parent_alpha_id: BRAIN alpha ID of the parent expression
        conn: SQLite connection

    Returns:
        True if parent is too correlated (skip sim), False if sim should proceed
    """
    try:
        row = conn.execute(
            "SELECT pnl_path FROM alphas WHERE alpha_id=?",
            (parent_alpha_id,),
        ).fetchone()
        if not row or not row[0]:
            return False  # no PnL for parent → cannot gate → allow sim

        parent_pnl_path = row[0]

        limit_val = get_selfcorr_limit(conn)
        if limit_val is None:
            return False  # no limit in DB → cannot gate → allow sim

        reference_paths = get_reference_pnl_paths(conn)
        if not reference_paths:
            return False  # no references → cannot gate → allow sim

        # WR-02: exclude the parent's own PnL path from the reference set.
        # If the parent is a PASS alpha, its path is in reference_paths; comparing
        # parent vs itself yields correlation 1.0, making proxy_gate return True for
        # every mutation of that parent — no mutations would ever be simulated.
        reference_paths = [p for p in reference_paths if p != parent_pnl_path]
        if not reference_paths:
            return False  # no references after excluding parent → allow sim

        return is_duplicate_by_pnl(parent_pnl_path, reference_paths, limit_val)
    except Exception:
        return False  # graceful degrade — never block grading


def backfill_active_pnl(
    client,
    conn: sqlite3.Connection,
    db_path: str = "alpha_kb.db",
    pnl_dir: str = "pnl_cache",
) -> int:
    """Fetch and cache PnL for all ACTIVE alphas that have no cached PnL yet.

    One-time backfill per D-12. Call this sequentially BEFORE the sim pool —
    do NOT call inside ≤3-concurrent sim workers (BRAIN throttle constraint).

    Auth constraint: 401 propagates immediately (never re-auth in-loop).
    Other fetch failures are logged and skipped (D-13).

    Args:
        client: BRAIN client with get_pnl(alpha_id) method
        conn: SQLite connection
        db_path: path to alpha_kb.db (informational, connection already open)
        pnl_dir: directory for PnL JSON cache files

    Returns:
        count of successfully fetched PnL records
    """
    rows = conn.execute(
        "SELECT alpha_id FROM alphas WHERE status='ACTIVE' AND pnl_path IS NULL"
    ).fetchall()

    count = 0
    for (alpha_id,) in rows:
        try:
            path = fetch_and_cache_pnl(client, alpha_id, conn, pnl_dir=pnl_dir)
            if path is not None:
                count += 1
        except requests.exceptions.HTTPError as e:
            if getattr(getattr(e, "response", None), "status_code", None) == 401:
                raise  # auth expiry — propagate immediately (CLAUDE.md)
            print(f"[selfcorr] backfill: HTTP error for {alpha_id}: {e}")
        except Exception as e:
            print(f"[selfcorr] backfill: skipping {alpha_id} — {e}")

    # Check available reference PnLs after backfill
    ref_paths = get_reference_pnl_paths(conn)
    if len(ref_paths) == 0:
        print(
            "[selfcorr] WARNING: zero reference PnLs cached after backfill — "
            "self-corr pre-filter is a no-op. Check pnl_cache/ and ACTIVE alpha_ids."
        )

    return count
