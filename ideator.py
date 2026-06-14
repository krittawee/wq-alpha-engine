"""ideator.py — Grounded Ideator for the Alpha Discovery System.

Turns a thesis dict (from researcher.build_thesis) into 4-8 FastExpr candidate
expressions drawn from the grounded archetype skeletons. Every candidate is:
  - composed from ONLY catalog-verified tokens (operators.name / datafields.id)
  - gated through validate.validate(conn, expr) — criterion 2
  - deduped via db.expr_exists(conn, expr) — criterion 3
  - tagged with the thesis archetype (D-04 inheritance; one thesis = one archetype)

No grade/simulate/BRAIN API calls are made here.

Public API:
    generate_candidates(conn, thesis, n=None) -> list[dict]
    queueable(candidates) -> list[dict]
    to_seeds_text(candidates) -> str
"""

import itertools
import re
import sqlite3
from typing import Optional

import db
import researcher
import validate

# ---------------------------------------------------------------------------
# Archetype skeleton expressions (LOCKED — 02-GROUNDING.md §Archetype taxonomy)
# These are the canonical grounded skeletons. Each passes validate.validate.
# NOTE: winsorize uses std= named param (BRAIN catalog: winsorize(x, std=4)).
# NOTE: nws12_afterhsz_sl is VECTOR type — always wrapped in vec_avg.
# ---------------------------------------------------------------------------

_SKELETONS: dict[str, str] = {
    "reversal": "rank(reverse(ts_delta(close, 5)))",
    "momentum": "rank(ts_decay_linear(ts_delta(ts_delay(close, 21), 231), 5))",
    "value_garp": "group_neutralize(winsorize(rank(divide(bookvalue_ps, close)), std=4), industry)",
    "quality": "group_zscore(rank(divide(operating_income, assets)), industry)",
    "growth": "rank(divide(ts_delta(actual_sales_value_annual, 252), abs(ts_delay(actual_sales_value_annual, 252))))",
    "low_volatility": "rank(reverse(ts_std_dev(returns, 60)))",
    "liquidity_volume": "trade_when(greater(ts_zscore(volume, 20), 1), rank(ts_corr(close, volume, 20)), -1)",
    # vec_avg wraps VECTOR field nws12_afterhsz_sl per steering notes
    "sentiment_event": "group_neutralize(rank(ts_decay_linear(ts_mean(vec_avg(nws12_afterhsz_sl), 5), 5)), industry)",
}

# ---------------------------------------------------------------------------
# Variation parameters: windows, normalizers, neut groups (all catalog-present)
# ---------------------------------------------------------------------------

# Alternative window values per archetype (numeric literals — never flagged by validator)
_WINDOW_VARIANTS: dict[str, list[int]] = {
    "reversal": [3, 5, 10, 20],
    "momentum": [5, 10, 21, 42],
    "value_garp": [],  # no window variation in skeleton
    "quality": [],
    "growth": [21, 63, 126, 252],
    "low_volatility": [20, 40, 60, 120],
    "liquidity_volume": [10, 20, 30, 60],
    "sentiment_event": [3, 5, 10, 20],
}

# Group neutralization fields (all confirmed GROUP type in catalog)
_NEUT_GROUPS = ["industry", "subindustry", "sector"]

# Cross-sectional normalizers (catalog-verified operators)
_NORMALIZERS = ["rank", "zscore"]

# VECTOR fields that require vec_avg wrapping (sourced from catalog type=VECTOR)
_VECTOR_FIELDS = frozenset({"nws12_afterhsz_sl"})


def _wrap_vector(field: str) -> str:
    """Wrap VECTOR-type fields in vec_avg per steering notes."""
    if field in _VECTOR_FIELDS:
        return f"vec_avg({field})"
    return field


def _make_reversal_variants(ops: list[str], fields: list[str]) -> list[str]:
    """Compose reversal candidates: rank(reverse(ts_delta(field, window)))."""
    candidates = [_SKELETONS["reversal"]]  # skeleton always first

    # Substitute alternate price/return fields from thesis if available
    alt_fields = [f for f in fields if f in {"returns", "vwap"}]
    for f in alt_fields:
        candidates.append(f"rank(reverse(ts_delta({_wrap_vector(f)}, 5)))")

    # Window variations on close
    for w in [3, 10, 20]:
        expr = f"rank(reverse(ts_delta(close, {w})))"
        if expr not in candidates:
            candidates.append(expr)

    # ts_zscore variant
    if "ts_zscore" in ops:
        candidates.append("rank(reverse(ts_zscore(close, 20)))")

    # group_neutralize wrapper variant
    if "group_neutralize" in ops:
        candidates.append(
            "group_neutralize(rank(reverse(ts_delta(close, 5))), industry)"
        )

    return candidates


def _make_momentum_variants(ops: list[str], fields: list[str]) -> list[str]:
    """Compose momentum candidates: rank(ts_decay_linear(ts_delta(ts_delay(field, lookback), signal), decay))."""
    candidates = [_SKELETONS["momentum"]]

    # window variations
    for lookback, signal, decay in [(5, 63, 5), (21, 126, 10), (42, 252, 21)]:
        expr = f"rank(ts_decay_linear(ts_delta(ts_delay(close, {lookback}), {signal}), {decay}))"
        if expr not in candidates:
            candidates.append(expr)

    # returns field variant
    if "returns" in fields:
        candidates.append("rank(ts_decay_linear(ts_mean(returns, 21), 5))")

    # group_neutralize wrapper
    if "group_neutralize" in ops:
        candidates.append(
            "group_neutralize(rank(ts_decay_linear(ts_delta(close, 21), 5)), industry)"
        )

    return candidates


def _make_value_garp_variants(ops: list[str], fields: list[str]) -> list[str]:
    """Compose value_garp candidates using fundamental ratio fields."""
    candidates = [_SKELETONS["value_garp"]]

    # mdl177 analyst model ratio
    if "mdl177_garpanalystmodel_qgp_vfpriceratio" in fields:
        candidates.append(
            "group_neutralize(rank(mdl177_garpanalystmodel_qgp_vfpriceratio), industry)"
        )

    # winsorize variant with subindustry neut
    candidates.append(
        "group_neutralize(winsorize(rank(divide(bookvalue_ps, close)), std=4), subindustry)"
    )

    # cashflow_op / cap ratio
    if "cashflow_op" in fields and "cap" in fields:
        candidates.append(
            "group_neutralize(rank(divide(cashflow_op, cap)), industry)"
        )

    # EPS ratio variant
    if "actual_eps_value_quarterly" in fields and "close" in fields:
        candidates.append(
            "group_neutralize(winsorize(rank(divide(actual_eps_value_quarterly, close)), std=4), industry)"
        )

    return candidates


def _make_quality_variants(ops: list[str], fields: list[str]) -> list[str]:
    """Compose quality candidates using fundamental quality ratios."""
    candidates = [_SKELETONS["quality"]]

    # operating_income/cap ratio
    if "cap" in fields and "operating_income" in fields:
        candidates.append("group_zscore(rank(divide(operating_income, cap)), industry)")

    # cashflow_op/assets ratio
    if "cashflow_op" in fields and "assets" in fields:
        candidates.append("group_zscore(rank(divide(cashflow_op, assets)), industry)")

    # subindustry neut variant
    candidates.append("group_zscore(rank(divide(operating_income, assets)), subindustry)")

    # winsorize wrapper
    if "winsorize" in ops:
        candidates.append(
            "group_neutralize(winsorize(rank(divide(operating_income, assets)), std=4), industry)"
        )

    # debt_lt ratio (leverage/quality signal)
    if "debt_lt" in fields and "assets" in fields:
        candidates.append("group_zscore(rank(divide(debt_lt, assets)), industry)")

    return candidates


def _make_growth_variants(ops: list[str], fields: list[str]) -> list[str]:
    """Compose growth candidates using sales/earnings growth ratios."""
    candidates = [_SKELETONS["growth"]]

    # shorter lookback window
    candidates.append(
        "rank(divide(ts_delta(actual_sales_value_annual, 63), abs(ts_delay(actual_sales_value_annual, 63))))"
    )

    # adj_net_income_avg variant
    if "adj_net_income_avg" in fields:
        candidates.append(
            "rank(divide(ts_delta(adj_net_income_avg, 252), abs(ts_delay(adj_net_income_avg, 252))))"
        )
        candidates.append(
            "rank(divide(ts_delta(adj_net_income_avg, 63), abs(ts_delay(adj_net_income_avg, 63))))"
        )

    # EPS growth variant
    if "actual_eps_value_quarterly" in fields:
        candidates.append(
            "rank(ts_delta(actual_eps_value_quarterly, 21))"
        )

    # group_neutralize wrapper
    if "group_neutralize" in ops:
        candidates.append(
            "group_neutralize(rank(divide(ts_delta(actual_sales_value_annual, 252), abs(ts_delay(actual_sales_value_annual, 252)))), industry)"
        )

    return candidates


def _make_low_volatility_variants(ops: list[str], fields: list[str]) -> list[str]:
    """Compose low_volatility candidates."""
    candidates = [_SKELETONS["low_volatility"]]

    # Alternative windows
    for w in [20, 40, 120]:
        expr = f"rank(reverse(ts_std_dev(returns, {w})))"
        if expr not in candidates:
            candidates.append(expr)

    # group_neutralize wrapper
    if "group_neutralize" in ops:
        candidates.append(
            "group_neutralize(rank(reverse(ts_std_dev(returns, 60))), industry)"
        )
        candidates.append(
            "group_neutralize(rank(reverse(ts_std_dev(returns, 20))), subindustry)"
        )

    return candidates


def _make_liquidity_volume_variants(ops: list[str], fields: list[str]) -> list[str]:
    """Compose liquidity_volume candidates using volume/price correlation."""
    candidates = [_SKELETONS["liquidity_volume"]]

    # Alternative correlation windows
    for w in [10, 30, 60]:
        expr = f"trade_when(greater(ts_zscore(volume, {w}), 1), rank(ts_corr(close, volume, {w})), -1)"
        if expr not in candidates:
            candidates.append(expr)

    # adv20 variant
    if "adv20" in fields:
        candidates.append("rank(reverse(ts_zscore(divide(volume, adv20), 20)))")

    # vwap/close ratio
    if "vwap" in fields:
        candidates.append("rank(ts_corr(close, vwap, 20))")

    return candidates


def _make_sentiment_event_variants(ops: list[str], fields: list[str]) -> list[str]:
    """Compose sentiment_event candidates using news/analyst signals."""
    candidates = [_SKELETONS["sentiment_event"]]

    # Alternative windows on the sentiment signal
    for decay_w in [3, 10, 20]:
        for mean_w in [3, 10]:
            expr = (
                f"group_neutralize(rank(ts_decay_linear("
                f"ts_mean(vec_avg(nws12_afterhsz_sl), {mean_w}), {decay_w})), industry)"
            )
            if expr not in candidates:
                candidates.append(expr)

    # subindustry neut variant
    candidates.append(
        "group_neutralize(rank(ts_decay_linear(ts_mean(vec_avg(nws12_afterhsz_sl), 5), 5)), subindustry)"
    )

    # adj_net_income_avg combo (if available)
    if "adj_net_income_avg" in fields:
        candidates.append(
            "group_neutralize(rank(ts_delta(adj_net_income_avg, 21)), industry)"
        )

    return candidates


# Dispatch table: archetype -> variant-generation function
_VARIANT_FNS = {
    "reversal": _make_reversal_variants,
    "momentum": _make_momentum_variants,
    "value_garp": _make_value_garp_variants,
    "quality": _make_quality_variants,
    "growth": _make_growth_variants,
    "low_volatility": _make_low_volatility_variants,
    "liquidity_volume": _make_liquidity_volume_variants,
    "sentiment_event": _make_sentiment_event_variants,
}


def _compose_expressions(thesis: dict) -> list[str]:
    """Produce grounded candidate expression strings for the thesis archetype.

    Uses only thesis.source_operators and thesis.source_datafields (catalog-
    verified subsets from researcher.build_thesis) plus the locked skeleton.
    Returns a deduplicated list (preserving order) of expression strings.
    """
    archetype = thesis["archetype"]
    ops = thesis.get("source_operators", [])
    fields = thesis.get("source_datafields", [])

    variant_fn = _VARIANT_FNS.get(archetype)
    if variant_fn is None:
        # Fallback: just return the skeleton
        return [_SKELETONS[archetype]]

    exprs = variant_fn(ops, fields)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for e in exprs:
        if e not in seen:
            seen.add(e)
            unique.append(e)

    return unique


# ---------------------------------------------------------------------------
# Bounded padding helper (CR-02: replaces the fragile \b5\b while-loop)
# ---------------------------------------------------------------------------

_WINDOW_SUBS = [3, 7, 10, 15, 20, 30, 45, 60, 90, 120]
_DIGIT_PATTERN = re.compile(r'\b(\d+)\b')


def _pad_to_min(all_exprs: list, skeleton: str, min_count: int) -> list:
    """Pad all_exprs to at least min_count using window substitution; always terminates.

    Finds the first numeric literal in the skeleton and substitutes window
    values from _WINDOW_SUBS.  If the skeleton has no numeric literal, returns
    all_exprs unchanged (cannot pad — no digit to substitute).
    """
    if len(all_exprs) >= min_count:
        return all_exprs
    m = _DIGIT_PATTERN.search(skeleton)
    if m is None:
        # No digit to substitute — return what we have
        return all_exprs
    for w in _WINDOW_SUBS:
        perturbed = skeleton[: m.start()] + str(w) + skeleton[m.end() :]
        if perturbed not in all_exprs:
            all_exprs.append(perturbed)
        if len(all_exprs) >= min_count:
            break
    return all_exprs


def generate_candidates(
    conn: sqlite3.Connection,
    thesis: dict,
    n: Optional[int] = None,
    delay: Optional[int] = None,
) -> list[dict]:
    """Generate 4-8 FastExpr candidate records from a thesis dict.

    Parameters
    ----------
    conn:   Open sqlite3.Connection (from db.init_db) — passed to validate/dedup.
    thesis: Dict from researcher.build_thesis. Required keys: archetype,
            source_operators, source_datafields.
    n:      Desired count. Clamped to [4, 8]. If None, uses all grounded variants
            (up to 8, at least 4).
    delay:  When provided (int), dedup is keyed on (expression, delay) so that a
            delay-0 candidate is NOT dropped because the same expression exists
            under delay=1.  When None (default), dedup uses expression only —
            preserving existing behavior for all callers that do not pass delay.

    Returns
    -------
    List of candidate dicts:
        expression:         str — FastExpr string
        archetype:          str — inherited from thesis (D-04)
        valid:              bool — True if validate.validate passes
        validation_reason:  str — "" if valid, else the rejection reason
        dedup_alpha_id:     Optional[str] — existing alpha_id if duplicate
                            under the same (expression, delay) key, else None

    Criterion 2 (no unknown-token rejections for queueable set): composition
    logic uses ONLY catalog-present tokens. Any candidate that fails validate
    (e.g. from a future catalog change) is marked invalid and excluded from
    queueable; this function still returns them for transparency.

    Criterion 3 (dedup): db.expr_exists is called on every candidate; duplicates
    are marked with dedup_alpha_id != None and excluded from queueable.

    No grade/simulate/BRAIN API calls are made here.
    """
    archetype = thesis["archetype"]

    # 1. Compose grounded expression strings
    all_exprs = _compose_expressions(thesis)

    # 2. Clamp count to [4, 8]
    min_count, max_count = 4, 8
    if n is not None:
        target = max(min_count, min(n, max_count))
    else:
        target = max_count

    # Ensure we have at least min_count by repeating the skeleton with minor
    # window perturbations if the variant list is too short (guards edge cases).
    # _pad_to_min is bounded — no infinite loop (CR-02).
    skeleton = _SKELETONS[archetype]
    all_exprs = _pad_to_min(all_exprs, skeleton, min_count)

    # Trim to target count
    exprs = all_exprs[:target]

    # 3. Build candidate records: run validate gate + dedup check
    candidates: list[dict] = []
    for expr in exprs:
        valid, reason = validate.validate(conn, expr)
        dedup_id = db.expr_exists(conn, expr, delay=delay)
        candidates.append({
            "expression": expr,
            "archetype": archetype,  # D-04 inheritance
            "valid": valid,
            "validation_reason": reason,
            "dedup_alpha_id": dedup_id,
        })

    return candidates


def queueable(candidates: list[dict]) -> list[dict]:
    """Return candidates that are both valid and novel (not in alphas.expression).

    Criterion 2: valid==True (validate.validate passed — no unknown tokens).
    Criterion 3: dedup_alpha_id is None (db.expr_exists returned None).
    """
    return [c for c in candidates if c["valid"] and c["dedup_alpha_id"] is None]


def to_seeds_text(candidates: list[dict], header: Optional[str] = None) -> str:
    """Serialize queueable candidates to seeds.txt format.

    Matches cli.py:62-64 parse contract:
        expressions = [l.strip() for l in lines if l.strip() and not l.startswith('#')]

    Parameters
    ----------
    candidates: List of candidate dicts from generate_candidates.
    header:     Optional comment string for a leading '#' line (default: archetype tag).

    Returns
    -------
    String with one FastExpr per line for queueable candidates. A leading
    '#'-prefixed comment line is included (skipped by cli.py). Blank lines
    are not emitted (cli.py skips them, but cleaner without them).
    """
    # Guarantee any caller-supplied header is a comment line (WR-03).
    # cli.py parses non-'#' lines as live BRAIN expressions; an un-prefixed
    # header would be treated as a real expression to submit.
    if header is not None and not header.startswith("#"):
        header = f"# {header}"

    q = queueable(candidates)

    if not q:
        archetype = candidates[0]["archetype"] if candidates else "unknown"
        comment = header if header else f"# ideator: {archetype} — 0 queueable candidates"
        return comment

    archetype = q[0]["archetype"]
    if header is None:
        header = f"# ideator: {archetype} — {len(q)} queueable candidates"

    lines = [header] + [c["expression"] for c in q]
    return "\n".join(lines)
