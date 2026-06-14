"""run_delay0.py — Grounded delay-0 alpha discovery + simulation (Batch 2).

Research findings applied:
  - Volume surge (power(rank(volume_5/volume_252), 0.5)) is the proven delay=0 pattern
    (sharpe 1.73-2.16, fitness 1.11-1.46 in existing DB)
  - nws12_afterhsz_sl (after-hours news sentiment, VECTOR) + volume = top delay=0 combos
  - VWAP reversion is novel at delay=0 (used in best delay=1 alpha vR9QdJAd)
  - Pure returns-reversal fails LOW_FITNESS — excluded
  - All fields confirmed delay=0: volume, vwap, nws12_afterhsz_sl, open, close,
    opening_gap_percent, cap, sector, subindustry

Delay-0 = trade at today's close using same-day data.
Batch 2 skips resync (already done in batch 1).
"""

import uuid

import db
import grade
import researcher
import validate
from wq_login import login

DB_PATH = "alpha_kb.db"

# --- Grounded delay-0 candidate pool (Batch 3) ---
# Context: vol-surge, VWAP-reversion, gap-fade, and basic news+vol are all DUPED.
# Novel angles: vol-zscore, intraday range, high/low-based, multi-factor combinations,
# and variable-assignment expressions (now valid after validate.py fix).
# All fields confirmed delay=0. VECTOR fields wrapped in vec_avg.

_D0_CANDIDATES = [
    # 1. Vol z-score (novel normalisation — zscore vs rank)
    "zscore(ts_mean(volume,5)/ts_mean(volume,252))",

    # 2. Intraday range as a signal — high range = heightened activity → momentum
    "rank((high - low) / close)",

    # 3. Low-vol factor — low intraday vol stocks tend to outperform
    "rank(-(high - low) / close)",

    # 4. Vol surge × intraday range (volume confirms price range → continuation)
    (
        "vol = power(rank(ts_mean(volume,5)/ts_mean(volume,252)), 0.5);\n"
        "rng = rank((high - low) / close);\n"
        "vol * rng"
    ),

    # 5. News + VWAP combo: news-sentiment gating VWAP reversion
    # (all parts are DUPED separately, but this multi-line combination is novel)
    (
        "vol = power(rank(ts_mean(volume,5)/ts_mean(volume,252)), 0.5);\n"
        "news = rank(ts_sum(vec_avg(nws12_afterhsz_sl), 120));\n"
        "vol + news"
    ),

    # 6. Cap-weighted vol surge (large-cap stocks with vol surges)
    (
        "vsurge = power(rank(ts_mean(volume,5)/ts_mean(volume,252)), 0.5);\n"
        "capw = rank(cap);\n"
        "vsurge + capw"
    ),

    # 7. VWAP reversion gated by intraday range (large range → stronger reversion)
    (
        "vwap_rev = rank((vwap - close) / vwap);\n"
        "rng = rank((high - low) / close);\n"
        "vwap_rev * rng"
    ),

    # 8. Subindustry-neutral vol surge (finer granularity than sector-neutral)
    "group_neutralize(power(rank(ts_mean(volume,5)/ts_mean(volume,252)), 0.5), subindustry)",
]


def main():
    print("[delay0-b2] Authenticating...")
    client = login()
    conn = db.init_db(DB_PATH)

    # Research step: archetype rotation + insights (no resync needed — delay=0 already loaded)
    print("[delay0-b2] Building thesis via researcher...")
    thesis = researcher.build_thesis(conn)
    archetype = thesis["archetype"]
    print(f"[delay0-b2] Archetype: {archetype}")
    for ins in thesis.get("cited_insights", []):
        print(f"[delay0-b2]   Insight: {ins}")

    # Validate + dedup
    print(f"\n[delay0-b2] Validating {len(_D0_CANDIDATES)} candidates...")
    queueable = []
    for expr in _D0_CANDIDATES:
        ok, reason = validate.validate(conn, expr)
        if not ok:
            print(f"[delay0-b2]   INVALID  {expr.splitlines()[0][:70]} — {reason}")
            continue
        dup = db.expr_exists(conn, expr)
        if dup:
            print(f"[delay0-b2]   DUPE     {expr.splitlines()[0][:70]} → {dup}")
            continue
        queueable.append(expr)
        print(f"[delay0-b2]   QUEUED   {expr.splitlines()[0][:70]}")

    if not queueable:
        print("[delay0-b2] No queueable candidates — all invalid or already graded.")
        conn.close()
        return

    # Simulate at delay=0
    run_id = str(uuid.uuid4())[:8]
    print(f"\n[delay0-b2] run_id={run_id}  simulating {len(queueable)} candidates at delay=0...")

    orig_delay = grade._BASE_SETTINGS["delay"]
    grade._BASE_SETTINGS["delay"] = 0
    try:
        results = grade.grade_many(
            client, conn, queueable, run_id, max_workers=3, db_path=DB_PATH
        )
    finally:
        grade._BASE_SETTINGS["delay"] = orig_delay

    # Ranked results
    print("\n--- Delay-0 Batch 2 results ---")
    hdr = f"{'#':>3}  {'expression':<60}  {'sharpe':>8}  {'fitness':>8}  {'self_corr':>9}  status"
    print(hdr)
    print("-" * len(hdr))
    for i, r in enumerate(
        sorted(results, key=lambda r: (r.get("sharpe") is None, -(r.get("sharpe") or 0))),
        1,
    ):
        sh, fi, sc = r.get("sharpe"), r.get("fitness"), r.get("self_corr")
        sh_str = f"{sh:8.4f}" if sh is not None else f"{'N/A':>8}"
        fi_str = f"{fi:8.4f}" if fi is not None else f"{'N/A':>8}"
        sc_str = f"{sc:9.4f}" if sc is not None else f"{'N/A':>9}"
        first_line = (r.get("expression") or "").splitlines()[0][:60]
        print(f"{i:>3}  {first_line:<60}  {sh_str}  {fi_str}  {sc_str}  {r.get('status')}")

    survivors = [r for r in results if r.get("status") == "pass"]
    if survivors:
        best = max(survivors, key=lambda r: r.get("sharpe") or 0)
        print(f"\nBest survivor: {best['expression'].splitlines()[0]}")
        print(f"  sharpe={best.get('sharpe')}  fitness={best.get('fitness')}  self_corr={best.get('self_corr')}")
    else:
        print("\nNo IS survivors at delay=0 in batch 2.")

    conn.close()
    print("[delay0-b2] Done.")


if __name__ == "__main__":
    main()
