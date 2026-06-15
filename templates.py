"""templates.py — Parameterized alpha template shapes for /bruteforce.

Templates are in-repo Python data structures (D-01). Slot expansion queries the live
catalog (datafields table). Probe-spread sampling covers all distinct slot values.
No external model dependencies. All VECTOR-type fields must be wrapped in vec_avg() in
expression templates (pitfall 3).

Exports:
    TEMPLATES — list of 4 ACE-inspired template shape dicts
    expand_slots(conn, template) -> list[tuple[str, dict]]
    probe_spread_sample(combos, slot_names, size=5) -> list
"""

import itertools
import sqlite3
from typing import Any, Dict, List, Tuple


# ---------------------------------------------------------------------------
# TEMPLATES — 4 ACE-inspired shapes (D-02)
# ---------------------------------------------------------------------------
# Each template is a dict with the following keys:
#   name             : snake_case identifier
#   archetype        : key into optimizer.ARCHETYPE_HEURISTICS (for settings grid)
#   description      : one-sentence human-readable purpose
#   slots            : dict of slot_name -> (list of literals OR catalog filter dict)
#   expression       : FastExpr template string using {slot_name} placeholders
#   settings_archetype: string key into ARCHETYPE_HEURISTICS (same as archetype here)
#
# VECTOR-type fields MUST be wrapped in vec_avg() in the expression template (pitfall 3).
# Never include "regular" as a settings key (buggy simulate() param — use default).
# All field tokens in literal slots are drawn from CLAIMED_DELAY0_FIELDS or confirmed
# delay-0 capable via prior probe runs.
# ---------------------------------------------------------------------------

TEMPLATES: List[Dict[str, Any]] = [
    # -----------------------------------------------------------------------
    # 1. sentiment_rank — rank of sentiment signal over a window (delay-0 safe)
    #    VECTOR fields (nws12 dataset) MUST be wrapped in vec_avg().
    #    slots.field: catalog-expanded from nws12 VECTOR fields
    #    slots.window: literal window sizes (days)
    # -----------------------------------------------------------------------
    {
        "name": "sentiment_rank",
        "archetype": "sentiment_event",
        "description": "Rank of cumulative sentiment signal over a rolling window",
        "slots": {
            "field": {"dataset": "nws12", "type": "VECTOR"},  # catalog-expanded; wrap in vec_avg
            "window": [5, 10, 20],  # literal window values
        },
        "expression": "rank(ts_sum(vec_avg({field}), {window}))",
        "settings_archetype": "sentiment_event",
    },

    # -----------------------------------------------------------------------
    # 2. fundamental_value — rank of fundamental ratio over a window
    #    MATRIX fields from fundamental6 dataset.
    #    slots.field: catalog-expanded from fundamental6 MATRIX fields
    #    slots.window: literal window sizes for ts_mean smoothing
    # -----------------------------------------------------------------------
    {
        "name": "fundamental_value",
        "archetype": "value_garp",
        "description": "Rank of smoothed fundamental ratio as a value signal",
        "slots": {
            "field": {"dataset": "fundamental6", "type": "MATRIX"},  # catalog-expanded
            "window": [5, 10, 20],  # literal window values
        },
        "expression": "rank(ts_mean({field}, {window}))",
        "settings_archetype": "value_garp",
    },

    # -----------------------------------------------------------------------
    # 3. residual_momentum — price momentum residual (delay-0 confirmed fields)
    #    Uses 'close' from CLAIMED_DELAY0_FIELDS (confirmed via alpha e7rvXqwz).
    #    Computes fast/slow MA ratio to capture momentum signal.
    #    slots.fast: literal fast window sizes
    #    slots.slow: literal slow window sizes
    # -----------------------------------------------------------------------
    {
        "name": "residual_momentum",
        "archetype": "momentum",
        "description": "Rank of price momentum (fast MA / slow MA - 1) using delay-0 close",
        "slots": {
            "fast": [3, 5, 10],   # literal fast window values
            "slow": [20, 40, 60],  # literal slow window values
        },
        "expression": "rank(ts_mean(close, {fast}) / ts_mean(close, {slow}) - 1)",
        "settings_archetype": "momentum",
    },

    # -----------------------------------------------------------------------
    # 4. beta_neutral — volume-weighted return relative to market
    #    Uses literal delay-0 confirmed fields: volume, vwap (CLAIMED_DELAY0_FIELDS).
    #    Computes cross-sectional rank of time-series correlation with close.
    #    slots.window: literal window sizes
    #    slots.field: literal list of confirmed delay-0 DOUBLE/MATRIX fields
    # -----------------------------------------------------------------------
    {
        "name": "beta_neutral",
        "archetype": "reversal",
        "description": "Rank of correlation between a volume/price field and close over a window",
        "slots": {
            "window": [5, 10, 20],
            "field": ["volume", "vwap"],  # literal — confirmed delay-0 from CLAIMED_DELAY0_FIELDS
        },
        "expression": "rank(ts_corr({field}, close, {window}))",
        "settings_archetype": "reversal",
    },
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _expand_one_slot(conn: sqlite3.Connection, slot_def: Any) -> List[str]:
    """Return list of string values for a single slot definition.

    Args:
        conn: SQLite connection with datafields table populated.
        slot_def: Either a list of literal values, or a dict with optional
                  'dataset' and/or 'type' keys for a catalog filter query.

    Returns:
        List of string values (field id strings for catalog slots,
        coerced-to-str values for literal slots).

    Security: Only 'dataset' and 'type' keys from slot_def are used in the
    WHERE clause, and all values are passed as parameterized query arguments
    (never interpolated) — prevents SQL injection (T-07-02-01).
    """
    if isinstance(slot_def, list):
        # Literal list — return as-is (coerce each value to str for expression formatting)
        return [str(v) for v in slot_def]

    # Catalog filter dict: query SELECT DISTINCT id FROM datafields WHERE ...
    dataset = slot_def.get("dataset")
    type_ = slot_def.get("type")
    clauses: List[str] = []
    params: List[Any] = []

    if dataset:
        clauses.append("dataset=?")
        params.append(dataset)
    if type_:
        clauses.append("type=?")
        params.append(type_)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    # SELECT DISTINCT avoids duplicate field ids from composite PK (id, region, universe, delay, dataset)
    rows = conn.execute(
        f"SELECT DISTINCT id FROM datafields {where}", params
    ).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def expand_slots(
    conn: sqlite3.Connection, template: Dict[str, Any]
) -> List[Tuple[str, Dict[str, str]]]:
    """Expand all slots in a template and return (expression, slot_values) tuples.

    For each slot in template['slots']:
      - If the slot value is a list: use literals directly.
      - If the slot value is a dict: query datafields catalog with SELECT DISTINCT id.

    Builds the cartesian product of all slot value lists, then fills
    template['expression'] with each combo via str.format_map.

    Args:
        conn: SQLite connection (datafields table must be populated for catalog slots).
        template: A template dict from TEMPLATES.

    Returns:
        List of (filled_expr, slot_value_dict) tuples where:
          - filled_expr: FastExpr string with all {slot_name} placeholders replaced.
          - slot_value_dict: dict mapping each slot_name to the string value used.

    Security: expressions pass through validate.validate() in bruteforce.py before
    any BRAIN simulation is attempted (T-07-02-02). VECTOR-type fields are wrapped
    in vec_avg() inside the expression template itself (T-07-02-03).
    """
    slots: Dict[str, Any] = template["slots"]
    slot_names: List[str] = list(slots.keys())

    # Expand each slot to a list of string values
    expanded: List[List[str]] = [
        _expand_one_slot(conn, slots[name]) for name in slot_names
    ]

    # If any slot expanded to 0 values (e.g., catalog filter with no matches), return empty
    for values in expanded:
        if not values:
            return []

    # Cartesian product of all slot value lists
    combos: List[Tuple[str, Dict[str, str]]] = []
    for combo_vals in itertools.product(*expanded):
        slot_dict: Dict[str, str] = dict(zip(slot_names, combo_vals))
        try:
            filled_expr: str = template["expression"].format_map(slot_dict)
        except KeyError:
            # Template has a placeholder not covered by any slot — skip this combo
            continue
        combos.append((filled_expr, slot_dict))

    return combos


def probe_spread_sample(
    combos: List[Tuple[str, Dict[str, str]]],
    slot_names: List[str],
    size: int = 5,
) -> List[Tuple[str, Dict[str, str]]]:
    """Return a spread sample of combos covering every distinct slot value at least once.

    Implements the greedy-cover algorithm from 07-RESEARCH.md Q6:
      Stage 1 (greedy cover): iterate combos in order; pick a combo if it adds a
        new value in ANY slot dimension; stop when len(selected) >= size.
      Stage 2 (fill): fill remaining slots up to size from the front of unseen combos.

    This ensures that every distinct value for every slot is exercised by at least
    one probe sim — a stronger test of template viability than first-N or random
    sampling (D-06).

    Args:
        combos: List of (filled_expr, slot_value_dict) tuples from expand_slots.
        slot_names: List of slot dimension names (template['slots'].keys()).
        size: Maximum number of combos to return (default 5, --probe-size configurable).

    Returns:
        Subset of combos (in original order), length <= size.
    """
    if not combos or size <= 0:
        return []

    # Track which values have been covered for each slot dimension
    covered: List[set] = [set() for _ in slot_names]

    selected: List[Tuple[str, Dict[str, str]]] = []

    # Stage 1: greedy cover — pick combos that add new coverage in any slot dimension
    for combo in combos:
        if len(selected) >= size:
            break
        slot_dict = combo[1]
        useful = any(
            slot_dict.get(slot_names[i]) not in covered[i]
            for i in range(len(slot_names))
        )
        if useful:
            selected.append(combo)
            for i in range(len(slot_names)):
                val = slot_dict.get(slot_names[i])
                if val is not None:
                    covered[i].add(val)

    # Stage 2: fill remaining slots up to size from front of unseen combos
    if len(selected) < size:
        selected_set = set(id(c) for c in selected)
        remaining_after = [c for c in combos if id(c) not in selected_set]
        while len(selected) < size and remaining_after:
            selected.append(remaining_after.pop(0))

    return selected
