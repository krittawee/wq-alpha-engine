"""additivity.py — Phase 6 additivity gate.

rank_by_proxy (zero BRAIN calls) + confirm_additive (one BRAIN /check per finalist).
Reusable by Phase 7 (brute-force) and Phase 9 (/iterate) without modification.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import grade
import selfcorr

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROXY_MARGIN = 0.05   # D-02: pre-filter drops only when combined_corr > limit + PROXY_MARGIN
CONFIRM_LIMIT = 3     # max finalists sent to confirm_additive per run (see hunt.py Plan 3)


# ---------------------------------------------------------------------------
# AdditivityResult dataclass (ADD-04 dual API: float rank + bool filter)
# ---------------------------------------------------------------------------

@dataclass
class AdditivityResult:
    """Carries both a float rank score (combined_corr) and bool filters (additive, proxy_drop).

    rank_by_proxy fills combined_corr, max_pairwise_corr, proxy_drop, skipped.
    confirm_additive fills brain_* fields and additive.
    """
    alpha_id: str
    pnl_path: Optional[str]
    combined_corr: Optional[float]       # primary rank key; lower = more additive
    max_pairwise_corr: Optional[float]   # predicts BRAIN self_corr gate; max pairwise Pearson
    proxy_drop: bool                     # True = hard-dropped by D-02 pre-filter
    skipped: bool                        # True = PnL missing; ranked last
    # confirm_additive fills these:
    brain_self_corr: Optional[float] = None
    brain_self_corr_result: Optional[str] = None   # PASS / FAIL / PENDING
    brain_self_corr_limit: Optional[float] = None  # from live /check, NEVER hardcoded
    brain_prod_corr: Optional[float] = None
    brain_prod_corr_result: Optional[str] = None
    additive: Optional[bool] = None      # True = confirmed additive; False = rejected; None = inconclusive


# ---------------------------------------------------------------------------
# _combined_book_corr — local proxy, zero BRAIN calls
# ---------------------------------------------------------------------------

def _combined_book_corr(candidate_path: str, ref_paths: list) -> Optional[float]:
    """Correlate candidate daily returns against the summed book daily returns.

    Builds the combined-book PnL series by summing daily returns across all
    ACTIVE reference paths, then Pearson-correlates against the candidate.

    Args:
        candidate_path: path to candidate PnL JSON ({"dates": [...], "pnls": [...]})
        ref_paths: list of paths to book alpha PnL JSONs

    Returns:
        Pearson correlation float in [-1, 1], or None if insufficient data.
    """
    # Load candidate
    try:
        cand_data = json.loads(Path(candidate_path).read_text())
    except Exception:
        return None

    cand_dates = cand_data.get("dates", [])
    cand_pnls = cand_data.get("pnls", [])
    if not cand_dates or len(cand_dates) != len(cand_pnls):
        return None

    cand_map: dict = dict(zip(cand_dates, cand_pnls))
    if not cand_map:
        return None

    # Accumulate book daily returns per date across all references
    # book_map[date] = sum of daily returns from all book alphas on that date
    book_map: dict = {}
    refs_used = 0
    total_refs = len(ref_paths)

    for ref_path in ref_paths:
        try:
            ref_data = json.loads(Path(ref_path).read_text())
        except Exception:
            continue  # D-04: skip missing file, warn but don't block

        ref_dates = ref_data.get("dates", [])
        ref_pnls = ref_data.get("pnls", [])
        if not ref_dates or len(ref_dates) != len(ref_pnls):
            continue

        ref_map = dict(zip(ref_dates, ref_pnls))

        # Find overlap between this reference and the candidate
        overlap = sorted(set(ref_map) & set(cand_map))
        if len(overlap) < 2:
            continue  # need at least 2 dates to compute a daily return

        ref_pnl_seq = [ref_map[d] for d in overlap]
        ref_daily = selfcorr._pnls_to_daily_returns(ref_pnl_seq)

        # Accumulate into book_map on dates overlap[1:] (daily return covers D from D-1→D)
        for date, ret in zip(overlap[1:], ref_daily):
            book_map[date] = book_map.get(date, 0.0) + ret

        refs_used += 1

    # D-04: warn if some references were skipped
    if refs_used < total_refs and refs_used > 0:
        skipped_count = total_refs - refs_used
        print(f"[additivity] WARNING: {skipped_count} of {total_refs} book reference(s) skipped "
              f"(file missing or malformed) — proxy correlation based on {refs_used} reference(s)")

    if refs_used == 0 or not book_map:
        print("[additivity] WARNING: zero book references available — proxy correlation is unavailable")
        return None

    # Find dates present in both book_map and cand_map, sorted.
    # book_map keys are already daily-return dates (overlap[1:] from the ref loop above),
    # so overlap2 holds at most (initial_overlap - 1) entries.
    # We need len(overlap2) >= 61 so that:
    #   cand_rets = _pnls_to_daily_returns(61 values) → 60 daily returns
    #   book_rets = overlap2[1:] → 60 values
    #   n = min(60, 60) = 60 which satisfies n >= 60
    overlap2 = sorted(d for d in book_map if d in cand_map)

    if len(overlap2) < 61:
        return None

    # Candidate daily returns: len = len(overlap2) - 1 (Pitfall 5 off-by-one fix)
    # Taking cumulative PnL on overlap2 dates → daily returns covers overlap2[1:] implicitly
    cand_rets = selfcorr._pnls_to_daily_returns([cand_map[d] for d in overlap2])

    # Book daily returns on overlap2[1:] (skip first date — no predecessor in book series)
    book_rets = [book_map[d] for d in overlap2[1:]]

    n = min(len(cand_rets), len(book_rets))
    if n < 60:
        return None

    return selfcorr._pearson(cand_rets[:n], book_rets[:n])


# ---------------------------------------------------------------------------
# rank_by_proxy — sort candidates by additivity, zero BRAIN calls
# ---------------------------------------------------------------------------

def rank_by_proxy(
    candidates: list,
    conn,
    margin: float = PROXY_MARGIN,
) -> list:
    """Rank candidates by additivity using local PnL proxy. Zero BRAIN API calls.

    Returns candidates sorted ascending by combined_corr (most additive first).
    Candidates with missing PnL are appended last with skipped=True.
    Candidates where combined_corr > limit + margin have proxy_drop=True.

    Args:
        candidates: list of dicts with keys alpha_id (str) and pnl_path (Optional[str])
        conn: SQLite connection
        margin: soft pre-filter margin above BRAIN's self_corr limit (default PROXY_MARGIN)

    Returns:
        list of AdditivityResult sorted ascending by combined_corr; skipped last
    """
    ref_paths = selfcorr.get_book_pnl_paths(conn)
    if not ref_paths:
        print("[additivity] WARNING: book PnL reference set is empty — "
              "proxy rank unavailable; all candidates pass through")

    limit = selfcorr.get_selfcorr_limit(conn)
    if limit is None:
        print("[additivity] WARNING: SELF_CORRELATION limit not in DB — pre-filter disabled")

    ranked = []
    skipped_results = []

    for cand in candidates:
        alpha_id = cand["alpha_id"]
        pnl_path = cand.get("pnl_path")

        # No PnL → skip; append last
        if pnl_path is None or not Path(pnl_path).exists():
            skipped_results.append(AdditivityResult(
                alpha_id=alpha_id,
                pnl_path=pnl_path,
                combined_corr=None,
                max_pairwise_corr=None,
                proxy_drop=False,
                skipped=True,
            ))
            continue

        combined_corr = _combined_book_corr(pnl_path, ref_paths) if ref_paths else None

        # max_pairwise_corr: 0.0 when ref_paths is empty (graceful degrade D-04)
        if ref_paths:
            max_pairwise_corr = selfcorr.max_pearson(pnl_path, ref_paths)
        else:
            max_pairwise_corr = 0.0

        # D-02 soft pre-filter: drop only when WELL ABOVE limit + margin
        # When combined_corr is None (no data), never drop (D-04 principle)
        if combined_corr is not None and limit is not None and combined_corr > limit + margin:
            proxy_drop = True
        else:
            proxy_drop = False

        ranked.append(AdditivityResult(
            alpha_id=alpha_id,
            pnl_path=pnl_path,
            combined_corr=combined_corr,
            max_pairwise_corr=max_pairwise_corr,
            proxy_drop=proxy_drop,
            skipped=False,
        ))

    # Sort ascending by combined_corr (most additive first)
    # Items with combined_corr=None sort after items with a value
    ranked.sort(key=lambda r: (r.combined_corr is None, r.combined_corr if r.combined_corr is not None else 0.0))

    return ranked + skipped_results


# ---------------------------------------------------------------------------
# confirm_additive — one BRAIN /check call per finalist
# ---------------------------------------------------------------------------

def confirm_additive(
    client,
    alpha_id: str,
    conn,
    timeout: int = 300,
    interval: int = 15,
) -> AdditivityResult:
    """Confirm additivity with BRAIN's real correlation check. ONE BRAIN call per alpha.

    Reads limit from is.checks response (NEVER hardcoded).
    Returns AdditivityResult with additive=True/False/None (None = inconclusive).

    401 propagates immediately (never caught here).
    TimeoutError → additive=None + warning printed.
    PROD_CORRELATION is optional — its absence is not an error.

    Args:
        client: authenticated BRAIN client (must have ._session)
        alpha_id: BRAIN alpha ID
        conn: SQLite connection (to look up pnl_path)
        timeout: seconds before polling gives up (default 300)
        interval: polling interval in seconds (default 15)

    Returns:
        AdditivityResult with brain_* fields and additive set
    """
    # Look up pnl_path from DB
    row = conn.execute(
        "SELECT pnl_path FROM alphas WHERE alpha_id=?", (alpha_id,)
    ).fetchone()
    pnl_path = row[0] if row else None

    # Kick off BRAIN /check — 401 propagates immediately
    grade.trigger_correlation_check(client, alpha_id)

    # Poll until resolved (or timeout)
    try:
        corr_checks = grade.poll_correlation(client, alpha_id, timeout=timeout, interval=interval)
    except TimeoutError:
        print(f"[additivity] WARNING: correlation check timed out after {timeout}s for {alpha_id} — "
              f"marking as inconclusive (additive=None)")
        return AdditivityResult(
            alpha_id=alpha_id,
            pnl_path=pnl_path,
            combined_corr=None,
            max_pairwise_corr=None,
            proxy_drop=False,
            skipped=False,
            additive=None,
        )

    # Parse response
    sc = corr_checks.get("SELF_CORRELATION", {})
    pc = corr_checks.get("PROD_CORRELATION", {})

    self_result = sc.get("result")
    self_value = sc.get("value")
    self_limit = sc.get("limit")   # live limit from BRAIN /check — NEVER hardcode

    prod_value = pc.get("value")
    prod_result = pc.get("result")

    # Determine additive verdict from SELF_CORRELATION only
    # (PROD_CORRELATION absence is not an error per grade.py:540 docstring)
    if self_result is None:
        # SELF_CORRELATION absent from response — inconclusive
        additive = None
    elif self_result == "PASS":
        additive = True
    else:
        additive = False

    return AdditivityResult(
        alpha_id=alpha_id,
        pnl_path=pnl_path,
        combined_corr=None,
        max_pairwise_corr=None,
        proxy_drop=False,
        skipped=False,
        brain_self_corr=self_value,
        brain_self_corr_result=self_result,
        brain_self_corr_limit=self_limit,
        brain_prod_corr=prod_value,
        brain_prod_corr_result=prod_result,
        additive=additive,
    )
