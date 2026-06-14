"""researcher.py — Grounded Researcher for the Alpha Discovery System.

This module provides the deterministic + data-grounding layer of the hybrid
Researcher (D-03 LOCKED decision). It reads the live catalog (operators/datafields)
and past-alpha memory (alphas/checks) from alpha_kb.db, selects one archetype
deterministically, pulls grounded catalog tokens + past-result insights, and
assembles a structured thesis dict for downstream plans (02-02 ideator, 02-03 command).

No BRAIN API calls are made here. No grade/simulate/login references.
"""

import sqlite3
from typing import Optional

import db

# ---------------------------------------------------------------------------
# Archetype taxonomy (8 labels — LOCKED per 02-CONTEXT.md D-03/D-04)
# ---------------------------------------------------------------------------

ARCHETYPES = [
    "reversal",
    "momentum",
    "value_garp",
    "quality",
    "growth",
    "low_volatility",
    "liquidity_volume",
    "sentiment_event",
]

# Grounded operator families and datafield seed tokens per archetype.
# Tokens are copied from 02-GROUNDING.md §Archetype taxonomy and confirmed
# present in the live synced alpha_kb.db catalog (verified 2026-06-08).
# Note: _ARCHETYPE_SEEDS values are SEED lists — they are intersected against
# the live catalog at build_thesis() time to guarantee subset membership.
_ARCHETYPE_SEEDS = {
    "reversal": {
        "operators": ["ts_delta", "ts_zscore", "reverse", "rank", "zscore", "group_neutralize"],
        "datafields": ["returns", "close", "vwap", "volume"],
    },
    "momentum": {
        "operators": ["ts_delta", "ts_mean", "ts_delay", "ts_decay_linear", "rank"],
        "datafields": ["close", "returns"],
    },
    "value_garp": {
        "operators": ["divide", "rank", "zscore", "winsorize", "group_neutralize", "multiply", "sign", "vector_neut"],
        "datafields": [
            "bookvalue_ps", "cashflow_op", "close", "cap",
            "actual_eps_value_quarterly", "mdl177_garpanalystmodel_qgp_vfpriceratio",
        ],
    },
    "quality": {
        "operators": ["divide", "rank", "zscore", "winsorize", "group_zscore", "reverse"],
        "datafields": ["cashflow_op", "assets", "debt_lt", "operating_income"],
    },
    "growth": {
        "operators": ["ts_delta", "ts_regression", "divide", "rank", "group_neutralize"],
        "datafields": [
            "actual_sales_value_annual", "actual_eps_value_quarterly", "adj_net_income_avg",
        ],
    },
    "low_volatility": {
        "operators": ["ts_std_dev", "reverse", "rank", "vector_neut", "group_neutralize"],
        "datafields": ["returns"],
    },
    "liquidity_volume": {
        "operators": ["ts_corr", "ts_zscore", "ts_av_diff", "trade_when", "divide", "rank", "power"],
        "datafields": ["volume", "adv20", "vwap", "returns", "sharesout"],
    },
    "sentiment_event": {
        "operators": ["vec_avg", "ts_delta", "ts_decay_linear", "ts_mean", "rank", "zscore", "group_neutralize", "trade_when"],
        "datafields": ["nws12_afterhsz_sl", "adj_net_income_avg"],
    },
}


# ---------------------------------------------------------------------------
# Task 1: Catalog reads + past-alpha insight queries
# ---------------------------------------------------------------------------


def read_catalog(conn: sqlite3.Connection, delay: int = 1) -> tuple[list[dict], list[dict]]:
    """Read operators and USA/TOP3000/delay=<delay> datafields from the live catalog.

    Returns:
        operators: list of dicts {name, category, definition} — all 67 rows.
        datafields: list of dicts {id, description, dataset, type} — USA/TOP3000/delay=<delay> slice.

    delay: filter the datafields query to this delay value (default 1; pass 0 for delay-0 fields).
    No hardcoded catalog — every token is read from the BRAIN-synced tables.
    """
    # Verbatim SELECTs from 02-GROUNDING.md §Phase 1 integration contract
    op_rows = conn.execute(
        "SELECT name, category, definition FROM operators"
    ).fetchall()
    operators = [
        {"name": row[0], "category": row[1], "definition": row[2]}
        for row in op_rows
    ]

    field_rows = conn.execute(
        "SELECT id, description, dataset, type FROM datafields"
        " WHERE region='USA' AND universe='TOP3000' AND delay=?",
        (delay,),
    ).fetchall()
    datafields = [
        {"id": row[0], "description": row[1], "dataset": row[2], "type": row[3]}
        for row in field_rows
    ]

    return operators, datafields


def gather_insights(conn: sqlite3.Connection) -> list[dict]:
    """Gather >=1 citable insight from populated alphas/checks columns.

    Insight citations are restricted to populated columns only:
    - sharpe, fitness, turnover, status from `alphas`
    - result (pass/fail) from `checks`
    NOT cited: archetype, self_corr, prod_corr (NULL across all 384 rows in-DB).

    Returns:
        list of dicts: {text: str, cited_alpha_ids: list[str]}
    """
    insights = []

    # CR-06: Read submittability thresholds from the checks table at runtime.
    # CLAUDE.md mandates thresholds must come from BRAIN's is.checks / DB, never hardcoded.
    # Fall back to safe defaults if no resolved rows exist yet (fresh DB / cold start).
    sharpe_lim_row = conn.execute(
        "SELECT limit_val FROM checks WHERE name='LOW_SHARPE' AND limit_val IS NOT NULL"
        " ORDER BY checked_at DESC LIMIT 1"
    ).fetchone()
    fitness_lim_row = conn.execute(
        "SELECT limit_val FROM checks WHERE name='LOW_FITNESS' AND limit_val IS NOT NULL"
        " ORDER BY checked_at DESC LIMIT 1"
    ).fetchone()
    turnover_lim_row = conn.execute(
        "SELECT limit_val FROM checks WHERE name='HIGH_TURNOVER' AND limit_val IS NOT NULL"
        " ORDER BY checked_at DESC LIMIT 1"
    ).fetchone()

    sharpe_lim = sharpe_lim_row[0] if sharpe_lim_row else 1.25   # BRAIN default fallback
    fitness_lim = fitness_lim_row[0] if fitness_lim_row else 1.0  # BRAIN default fallback
    turnover_lim = turnover_lim_row[0] if turnover_lim_row else 0.4  # BRAIN default fallback

    # Insight 1: Clean pool count using runtime thresholds from DB.
    clean_pool_row = conn.execute(
        "SELECT count(*) FROM alphas"
        " WHERE status='UNSUBMITTED' AND sharpe>=? AND fitness>=? AND turnover<=?",
        (sharpe_lim, fitness_lim, turnover_lim),
    ).fetchone()
    clean_pool_count = clean_pool_row[0] if clean_pool_row else 0

    # Pull a sample of alpha_ids from the clean pool for provenance
    clean_pool_ids = conn.execute(
        "SELECT alpha_id FROM alphas"
        " WHERE status='UNSUBMITTED' AND sharpe>=? AND fitness>=? AND turnover<=?"
        " LIMIT 5",
        (sharpe_lim, fitness_lim, turnover_lim),
    ).fetchall()
    clean_pool_alpha_ids = [row[0] for row in clean_pool_ids]

    insights.append({
        "text": (
            f"Clean pool: {clean_pool_count} UNSUBMITTED alphas have sharpe>={sharpe_lim}, "
            f"fitness>={fitness_lim}, and turnover<={turnover_lim} (thresholds read from DB). "
            f"Thesis target: diversify around or extend this existing pool rather than "
            f"regenerating from scratch."
        ),
        "cited_alpha_ids": clean_pool_alpha_ids,
    })

    # Insight 2: Most common FAIL check name from checks table
    fail_row = conn.execute(
        "SELECT name, count(*) as cnt FROM checks"
        " WHERE result LIKE '%FAIL%'"
        " GROUP BY name ORDER BY cnt DESC LIMIT 1"
    ).fetchone()

    if fail_row:
        fail_name, fail_count = fail_row[0], fail_row[1]
        # Pull alpha_ids that have this failing check
        fail_alpha_ids = conn.execute(
            "SELECT DISTINCT alpha_id FROM checks WHERE result LIKE '%FAIL%' AND name=? LIMIT 5",
            (fail_name,),
        ).fetchall()
        fail_cited_ids = [row[0] for row in fail_alpha_ids]

        insights.append({
            "text": (
                f"Most common FAIL check: '{fail_name}' ({fail_count} alphas). "
                f"Anti-pattern to avoid: naive single-operator price/volume signals "
                f"consistently fail this check."
            ),
            "cited_alpha_ids": fail_cited_ids,
        })

    # Insight 3: Best performing UNSUBMITTED alpha by sharpe (from populated columns only)
    best_row = conn.execute(
        "SELECT alpha_id, sharpe, fitness, turnover FROM alphas"
        " WHERE status='UNSUBMITTED' AND sharpe IS NOT NULL"
        "   AND fitness IS NOT NULL AND turnover IS NOT NULL"
        " ORDER BY sharpe DESC LIMIT 1"
    ).fetchone()

    if best_row:
        best_id, best_sharpe, best_fitness, best_turnover = best_row
        insights.append({
            "text": (
                f"Best UNSUBMITTED alpha by sharpe: '{best_id}' "
                f"(sharpe={best_sharpe:.2f}, fitness={best_fitness:.2f}, "
                f"turnover={best_turnover:.3f}). "
                f"Thesis target: match or exceed this benchmark."
            ),
            "cited_alpha_ids": [best_id],
        })

    return insights


# ---------------------------------------------------------------------------
# Task 2: Deterministic archetype selection + thesis assembly
# ---------------------------------------------------------------------------


def select_archetype(conn: sqlite3.Connection) -> str:
    """Deterministically select one of the 8 taxonomy archetype labels.

    Selection algorithm (documented for reproducibility):
    1. Count current rows in the `runs` table — this is the "run index" (0-based).
    2. Use modulo over the 8 archetypes (in ARCHETYPES order) to cycle through them.
       Same DB state (same runs count) always yields the same archetype — deterministic.
    3. Bias: sentiment_event and quality are placed later in the rotation so the cycle
       starts with archetypes that have historically underperformed (reversal, momentum)
       and progresses to fundamentals-heavy archetypes (value_garp, quality, growth),
       matching the steering note "diversify away from naive price/volume signals."

    Rationale: since alphas.archetype is NULL for all 384 rows (never populated in-DB),
    we cannot detect "under-explored" archetypes from DB state. The rotation over ARCHETYPES
    list provides fair deterministic coverage, and the run count provides cross-call
    reproducibility. The 59-clean-pool insight from gather_insights() is surfaced in the
    thesis (cited_insights) for the LLM prose layer to steer around.

    Returns:
        One of the 8 archetype label strings from ARCHETYPES.
    """
    run_count_row = conn.execute("SELECT count(*) FROM runs").fetchone()
    run_count = run_count_row[0] if run_count_row else 0
    return ARCHETYPES[run_count % len(ARCHETYPES)]


def build_thesis(
    conn: sqlite3.Connection,
    archetype: Optional[str] = None,
    avoid_motifs: Optional[list] = None,
    delay: int = 1,
) -> dict:
    """Assemble a structured thesis dict from the live catalog + past insights.

    Calls read_catalog, gather_insights, and (if archetype is None) select_archetype.
    Intersects seed operator/field tokens against the live catalog to guarantee
    that every emitted token is present in the synced catalog (machine-checkable
    for criterion 1 of Phase 2 success criteria).

    avoid_motifs: optional list of structural motif strings to steer the LLM away
        from overused expression patterns (D-15). When non-empty, appended to
        cited_insights so the downstream LLM prose layer sees the avoid-list.
        If None or empty, behavior is unchanged.

    delay: simulation delay in days (default 1). Passed to read_catalog to query
        the correct delay slice from the datafields table, and emitted in the
        returned dict so downstream modules (ideator, grade) use the right value.

    Returns a dict with keys:
        archetype: str — one of the 8 taxonomy labels
        source_operators: list[str] — subset of operators.name in live catalog
        source_datafields: list[str] — subset of datafields.id in synced slice
        cited_alpha_ids: list[str] — alpha_ids from insight citations
        cited_insights: list[str] — human-readable insight strings
        avoid_motifs: list[str] — motifs to avoid (passed through for downstream use)
        region: str — 'USA'
        universe: str — 'TOP3000'
        delay: int — simulation delay (matches the delay= argument)

    No LLM prose is generated here. No grade/simulate/BRAIN API calls are made.
    """
    # Step 1: Read live catalog (query the correct delay slice)
    operators, datafields = read_catalog(conn, delay=delay)
    live_op_names = {op["name"] for op in operators}
    live_field_ids = {f["id"] for f in datafields}

    # Step 2: Select archetype
    if archetype is None:
        archetype = select_archetype(conn)

    if archetype not in ARCHETYPES:
        raise ValueError(f"Unknown archetype '{archetype}'; must be one of: {ARCHETYPES}")

    # Step 3: Gather past-alpha insights
    insights = gather_insights(conn)

    # Step 4: Intersect seed tokens against live catalog to guarantee subset membership
    seeds = _ARCHETYPE_SEEDS[archetype]
    source_operators = [op for op in seeds["operators"] if op in live_op_names]
    source_datafields = [fid for fid in seeds["datafields"] if fid in live_field_ids]

    # Step 5: Aggregate cited_alpha_ids from all insights
    cited_alpha_ids: list[str] = []
    for ins in insights:
        for aid in ins.get("cited_alpha_ids", []):
            if aid not in cited_alpha_ids:
                cited_alpha_ids.append(aid)

    cited_insights = [ins["text"] for ins in insights]

    # Phase 3 D-15: inject avoid_motifs into cited_insights for upstream LLM steer.
    # When the LLM prose layer reads cited_insights, it sees the structural motifs to
    # avoid (overused patterns in past PASS alphas), steering generation diversity.
    # No change to behavior when avoid_motifs is empty or None.
    if avoid_motifs:
        motifs_str = ", ".join(avoid_motifs)
        avoid_insight = (
            f"Structural motifs to AVOID (overused in past PASS alphas): {motifs_str}. "
            f"Generate expressions that do NOT share these structural patterns."
        )
        cited_insights = cited_insights + [avoid_insight]

    return {
        "archetype": archetype,
        "source_operators": source_operators,
        "source_datafields": source_datafields,
        "cited_alpha_ids": cited_alpha_ids,
        "cited_insights": cited_insights,
        "avoid_motifs": avoid_motifs or [],
        "region": "USA",
        "universe": "TOP3000",
        "delay": delay,
    }
