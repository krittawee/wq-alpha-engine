"""optimizer.py — Settings Optimizer for NEAR alphas.

OPT-01: For every NEAR alpha in the DB, build ≤4 settings variants from the
archetype heuristic table blended with past PASS settings, simulate them via
grade_many (single-shot auth, ≤3 concurrent sims), record outcomes back to DB
with parent_alpha_id, and regenerate Obsidian notes as a side-effect.

Public API:
    ARCHETYPE_HEURISTICS: dict — archetype → list of (decay, neutralization, truncation) tuples
    build_variants(alpha_row, conn) -> list[dict]
    run_optimize(client, conn=None, db_path="alpha_kb.db", max_workers=1) -> dict
"""

import uuid
from typing import Optional

import sqlite3

import db
import grade
import selfcorr

try:
    import obsidian as _obsidian_mod
except ImportError:
    _obsidian_mod = None  # obsidian.py not yet implemented — graceful degrade


# ---------------------------------------------------------------------------
# ARCHETYPE_HEURISTICS
# Keys: archetype labels from researcher.ARCHETYPES (8 labels, LOCKED D-03/D-04)
# Values: list of (decay, neutralization, truncation) tuples
# Derived from WorldQuant BRAIN parameter mechanics + observed PASS settings in DB
#   - decay: smooths noise; momentum/reversal benefit from low decay (signal freshness);
#            value/quality benefit from higher decay (fundamental signals are slow)
#   - neutralization: SUBINDUSTRY removes sector/industry bias; MARKET removes only
#            broad market beta; use INDUSTRY for moderately fine-grained control
#   - truncation: 0.08 is the dominant PASS value; 0.05 for concentrated strategies;
#            0.1 for factor-style alphas with many small positions
# ---------------------------------------------------------------------------

ARCHETYPE_HEURISTICS = {
    "reversal": [
        (5,  "SUBINDUSTRY", 0.08),  # short decay keeps reversal signal fresh
        (0,  "SUBINDUSTRY", 0.08),  # no decay = raw signal (often stronger for reversal)
        (3,  "INDUSTRY",    0.08),  # broader neutralization sometimes helps
        (2,  "SUBINDUSTRY", 0.05),  # tighter truncation for concentrated reversal
    ],
    "momentum": [
        (10, "SUBINDUSTRY", 0.08),  # medium decay for intermediate momentum
        (5,  "SUBINDUSTRY", 0.08),  # shorter decay for fast momentum
        (15, "INDUSTRY",    0.08),  # standard decay, broader neutralization
        (0,  "SUBINDUSTRY", 0.08),  # raw (momentum signals sometimes prefer no smoothing)
    ],
    "value_garp": [
        (20, "SUBINDUSTRY", 0.08),  # fundamental data slow-moving, high decay appropriate
        (15, "SUBINDUSTRY", 0.08),  # standard — matches default
        (10, "INDUSTRY",    0.08),  # medium decay, broader neutralization
        (25, "SUBINDUSTRY", 0.10),  # aggressive decay + wider truncation for value spread
    ],
    "quality": [
        (20, "SUBINDUSTRY", 0.08),
        (15, "INDUSTRY",    0.08),
        (10, "SUBINDUSTRY", 0.10),
        (25, "SUBINDUSTRY", 0.08),
    ],
    "growth": [
        (15, "SUBINDUSTRY", 0.08),
        (10, "SUBINDUSTRY", 0.08),
        (20, "INDUSTRY",    0.08),
        (5,  "SUBINDUSTRY", 0.10),
    ],
    "low_volatility": [
        (20, "SUBINDUSTRY", 0.05),  # low-vol benefits from concentrated positions
        (15, "SUBINDUSTRY", 0.08),
        (10, "MARKET",      0.08),  # market neutralization for pure vol signal
        (25, "SUBINDUSTRY", 0.05),
    ],
    "liquidity_volume": [
        (5,  "SUBINDUSTRY", 0.08),  # volume signals are short-lived
        (0,  "INDUSTRY",    0.08),
        (3,  "SUBINDUSTRY", 0.10),
        (10, "SUBINDUSTRY", 0.08),
    ],
    "sentiment_event": [
        (3,  "SUBINDUSTRY", 0.08),  # event signals decay fast
        (0,  "SUBINDUSTRY", 0.08),
        (5,  "INDUSTRY",    0.08),
        (1,  "SUBINDUSTRY", 0.05),
    ],
}


def build_variants(alpha_row: dict, conn: sqlite3.Connection) -> list:
    """Return ≤4 settings dicts for the given NEAR alpha.

    Strategy (D-02):
    1. Start from the archetype heuristic list for alpha.archetype.
       Defaults to "reversal" if archetype is None/empty (Pitfall 1 fallback).
    2. Query up to 10 unique (decay, neutralization, truncation) combos from
       PASS/ACTIVE alphas in the DB (excluding the exact settings the NEAR alpha
       already has), ordered by sharpe DESC.
    3. Merge: heuristics first, then PASS settings to fill remaining slots up to cap=4.
    4. Deduplicate: dedupe by (d,n,t) tuple.
    5. Build full settings dict for each variant by copying _BASE_SETTINGS and
       overriding decay/neutralization/truncation. region/universe/delay unchanged (D-01).

    Returns list of full settings dicts (len 0–4).
    Returns empty list if all heuristic combos match the current combo.
    """
    # Step 1: archetype with NULL fallback (Pitfall 1)
    archetype = alpha_row.get("archetype")
    if not archetype:
        print(f"[optimizer] WARNING: alpha {alpha_row.get('alpha_id')} has no archetype — defaulting to 'reversal'")
        archetype = "reversal"

    current = (alpha_row.get("decay"), alpha_row.get("neutralization"), alpha_row.get("truncation"))

    # Step 2: archetype heuristics, excluding current combo
    heuristic_combos = [
        c for c in ARCHETYPE_HEURISTICS.get(archetype, ARCHETYPE_HEURISTICS["reversal"])
        if tuple(c) != current
    ]

    # Step 3: past PASS/ACTIVE settings from DB (≤10 candidates, filter out current)
    rows = conn.execute(
        "SELECT DISTINCT decay, neutralization, truncation FROM alphas "
        "WHERE status IN ('pass', 'ACTIVE') AND decay IS NOT NULL "
        "AND neutralization IS NOT NULL AND truncation IS NOT NULL "
        "ORDER BY sharpe DESC LIMIT 10"
    ).fetchall()
    pass_combos = [r for r in rows if tuple(r) != current]

    # Step 4: merge, deduplicate by (d,n,t) tuple, cap at 4
    seen = set()
    candidates = []
    for combo in (heuristic_combos + pass_combos):
        key = tuple(combo)
        if key not in seen and len(candidates) < 4:
            seen.add(key)
            candidates.append(combo)

    # Step 5: build full settings dicts — copy _BASE_SETTINGS, override d/n/t (D-01)
    variants = []
    for combo in candidates:
        decay, neutralization, truncation = combo[0], combo[1], combo[2]
        s = dict(grade._BASE_SETTINGS)
        s["decay"] = decay
        s["neutralization"] = neutralization
        s["truncation"] = truncation
        variants.append(s)

    return variants


def run_optimize(
    client,
    conn: Optional[sqlite3.Connection] = None,
    db_path: str = "alpha_kb.db",
    max_workers: int = 1,
) -> dict:
    """Optimize all NEAR alphas in the DB by simulating settings variants.

    For each NEAR alpha:
    1. Run selfcorr.proxy_gate — skip if too correlated (saves sim slots).
    2. Call build_variants to get ≤4 settings dicts.
    3. For each variant, call grade.grade_many with settings_map and parent_map
       so lineage (parent_alpha_id) and settings are recorded in DB.
    4. After all NEAR alphas processed, call obsidian.regen_all as side-effect (D-11).

    conn: optional open SQLite connection. When provided (e.g., in tests), it is used
          directly for the NEAR alpha query and proxy_gate. grade_many still opens its
          own per-worker connections via db_path for thread safety.
    db_path: path to alpha_kb.db (used by grade_many workers).
    max_workers: concurrency cap passed to grade_many (BRAIN cap ≤3; default=1 sequential).

    Returns summary dict: {"near_alphas_processed": N, "variants_simulated": M, "variants_passed": K}.

    401 from BRAIN propagates immediately — never re-auth per CLAUDE.md.
    """
    # Open connection if not provided
    _own_conn = conn is None
    if _own_conn:
        conn = db.init_db(db_path)

    try:
        # Query all NEAR alphas
        rows = conn.execute(
            "SELECT alpha_id, expression, archetype, decay, neutralization, truncation "
            "FROM alphas WHERE status='near'"
        ).fetchall()

        near_cols = ["alpha_id", "expression", "archetype", "decay", "neutralization", "truncation"]
        near_alphas = [dict(zip(near_cols, r)) for r in rows]

        near_alphas_processed = 0
        variants_simulated = 0
        variants_passed = 0

        for near_alpha in near_alphas:
            near_alpha_id = near_alpha["alpha_id"]
            expression = near_alpha["expression"]

            # Step 1: proxy_gate — skip if NEAR alpha itself is too correlated
            if selfcorr.proxy_gate(near_alpha_id, conn):
                print(f"[optimizer] proxy-gate skip: {near_alpha_id}")
                continue

            # Step 2: build variants
            variants = build_variants(near_alpha, conn)
            if not variants:
                print(f"[optimizer] no variants for {near_alpha_id} — all combos match current settings")
                continue

            near_alphas_processed += 1

            # Step 3: simulate each variant sequentially (max_workers=1 per variant,
            # different settings per variant means they must run one-at-a-time)
            for variant_settings in variants:
                run_id = str(uuid.uuid4())
                results = grade.grade_many(
                    client=client,
                    conn=conn,
                    expressions=[expression],
                    run_id=run_id,
                    max_workers=1,
                    db_path=db_path,
                    parent_map={expression: near_alpha_id},
                    settings_map={expression: variant_settings},
                )
                for result in results:
                    status = result.get("status")
                    if status not in ("duplicate", "invalid", "error"):
                        variants_simulated += 1
                    if status == "pass":
                        variants_passed += 1

        # Step 4: regenerate Obsidian notes as side-effect (D-11)
        if _obsidian_mod is not None:
            try:
                _obsidian_mod.regen_all(conn)
            except Exception as e:
                print(f"[optimizer] WARNING: obsidian.regen_all failed — {e}")
        else:
            print("[optimizer] obsidian module not available — skipping note regeneration")

        return {
            "near_alphas_processed": near_alphas_processed,
            "variants_simulated": variants_simulated,
            "variants_passed": variants_passed,
        }

    finally:
        if _own_conn:
            conn.close()
