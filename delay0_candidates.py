"""delay0_candidates.py — Harvested delay-0 knowledge from run_delay0.py.

Origin:
    Harvested from run_delay0.py on 2026-06-12 per D-05 (harvest-then-retire).
    run_delay0.py was an ad-hoc batch script; this file preserves its useful
    knowledge (candidate expressions + field hypotheses) without the execution
    pattern.

Verification caveat:
    The field claims and candidate expressions in this file were produced by
    run_delay0.py, which coexisted with the delay-recording mislabeling bug
    (fixed 2026-06-11). All "confirmed delay=0" claims from that script must be
    treated as UNVERIFIED HYPOTHESES until re-confirmed via probe_delay.probe_and_gate().
    Do NOT treat any field or expression here as ground truth without a live probe.
"""


# ---------------------------------------------------------------------------
# CLAIMED delay-0 capable fields
# ---------------------------------------------------------------------------

# UNVERIFIED HYPOTHESIS — these fields were claimed as delay-0 capable by run_delay0.py
# but that script coexisted with the delay-recording mislabeling bug (2026-06-11 fix).
# Re-confirm via probe_delay.probe_and_gate() before treating any of these as ground truth.
# Use wording "claimed delay-0 field" not "confirmed delay-0 field" anywhere these are referenced.
CLAIMED_DELAY0_FIELDS = [
    "volume",
    "vwap",
    "nws12_afterhsz_sl",
    "open",
    "close",
    "opening_gap_percent",
    "cap",
    "sector",
    "subindustry",
]


# ---------------------------------------------------------------------------
# Candidate expressions for delay-0 simulation
# ---------------------------------------------------------------------------

# Context from run_delay0.py (Batch 3):
#   vol-surge, VWAP-reversion, gap-fade, and basic news+vol are all DUPED.
#   Novel angles: vol-zscore, intraday range, high/low-based, multi-factor
#   combinations, and variable-assignment expressions.
#   All fields claimed delay-0. VECTOR fields wrapped in vec_avg.
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


# ---------------------------------------------------------------------------
# Post-Test-B update protocol
# ---------------------------------------------------------------------------

def post_test_b_update_note():
    """Note on how to update probe settings after Plan 03 Test B bisection.

    If Test B (Plan 03) bisection finds that _BASE_SETTINGS causes BRAIN to coerce
    delay-0 to delay-1, and a specific settings shape fixes it, the update path is:

      1. Use run_probe(client, conn, requested_delay=0, settings_override=<new_settings>)
         to validate the new settings object before hardening it into the default.
      2. Once confirmed, update PROBE_EXPRESSION or probe_delay.py's default settings
         (the {**grade._BASE_SETTINGS, "delay": 0} dict construction) accordingly.
      3. Update this file's CLAIMED_DELAY0_FIELDS to CONFIRMED_DELAY0_FIELDS for any
         fields re-verified by the probe. Keep the unverified remainder as claimed only.

    The run_probe() call with settings_override= is the designed path to validate new
    settings without committing them to the default code path.
    """


# run_delay0.py retired 2026-06-12 per D-05. This file is the sole reference;
# delete this file too if the expressions are all confirmed dupes or invalidated by probe.
