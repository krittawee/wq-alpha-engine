"""fsa.py — Frequent Subtree Avoidance for the Alpha Discovery System.

Mines common structural motifs (abstract AST subtree shapes) from PASS
alphas in the DB. Returns an avoid-list that:
  - is injected into Researcher + Editor LLM prompts (upstream steer)
  - is applied as a post-generation filter in find_alphas / hunt (hard gate)

Uses Python stdlib ast only. Operates on status='pass' alphas —
never on ACTIVE user-submitted alphas (which may use ternary syntax).
"""

import ast
from collections import Counter
import sqlite3
from typing import Optional

# ---------------------------------------------------------------------------
# Module-level defaults (Claude's discretion per 03-CONTEXT.md)
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLD = 0.5   # motif must appear in >= 50% of PASS alphas
DEFAULT_MIN_SAMPLES = 5   # cold-start guard: return [] if fewer than this many PASS alphas


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _arg_type(node) -> str:
    """Return a string label for an AST node's role as a function argument."""
    if isinstance(node, ast.Call):
        return "CALL"
    if isinstance(node, ast.Constant):
        return "NUM" if isinstance(node.value, (int, float)) else "STR"
    if isinstance(node, ast.Name):
        return "FIELD"
    if isinstance(node, ast.BinOp):
        return "BINOP"
    return "_"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_abstract_subtrees(expr: str) -> list:
    """Extract operator-shape motifs from a FastExpr string.

    Each Call node is represented as "fname(TYPE1,TYPE2,...)" where TYPE is one of:
    CALL, NUM, STR, FIELD, BINOP, or _.

    Returns [] on SyntaxError (ternary-safe: BRAIN's ?:  syntax is not valid Python).
    Returns [] on any other parse error.

    Examples:
        extract_abstract_subtrees("ts_rank(close, 5)")
            -> ["ts_rank(FIELD,NUM)"]
        extract_abstract_subtrees("rank(ts_mean(close,20))")
            -> ["rank(CALL)", "ts_mean(FIELD,NUM)"]
        extract_abstract_subtrees("close ? open : high")
            -> []  (ternary — SyntaxError)
    """
    try:
        tree = ast.parse(expr.strip(), mode='eval')
    except SyntaxError:
        return []
    except Exception:
        return []

    shapes = []

    def _visit(node):
        if isinstance(node, ast.Call):
            fname = node.func.id if isinstance(node.func, ast.Name) else '?'
            arg_types = [_arg_type(a) for a in node.args]
            shapes.append(f"{fname}({','.join(arg_types)})")
        # WR-07: recurse into ALL child nodes (BinOp, UnaryOp, keyword, etc.)
        # Previously only ast.Call.args were visited; motifs inside arithmetic
        # combinations like "rank(close) - rank(open)" (BinOp) were invisible.
        for child in ast.iter_child_nodes(node):
            _visit(child)

    _visit(tree.body)
    return shapes


def mine_frequent_motifs(
    conn: sqlite3.Connection,
    threshold: float = DEFAULT_THRESHOLD,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> list:
    """Mine subtree motifs from PASS alphas. Returns motifs appearing in >= threshold fraction.

    Returns [] if fewer than min_samples PASS alphas exist (cold-start guard).
    Queries only status='pass' — never ACTIVE (ternary safety per 03-RESEARCH Pitfall 3).

    Args:
        conn: SQLite connection to alpha_kb.db.
        threshold: Minimum fraction of PASS alphas that must contain the motif.
        min_samples: Minimum number of PASS alphas required to mine motifs.

    Returns:
        List of motif strings that appear in >= threshold fraction of PASS alphas.
    """
    rows = conn.execute(
        "SELECT expression FROM alphas WHERE status='pass'"
    ).fetchall()

    pass_exprs = [row[0] for row in rows]

    if len(pass_exprs) < min_samples:
        return []  # cold-start guard

    # Count each motif at most once per alpha (use set per alpha)
    counter: Counter = Counter()
    for expr in pass_exprs:
        motifs_for_expr = set(extract_abstract_subtrees(expr))
        for motif in motifs_for_expr:
            counter[motif] += 1

    total = len(pass_exprs)
    return [motif for motif, cnt in counter.items() if cnt / total >= threshold]


def filter_candidates(candidates: list, avoid_motifs: list) -> list:
    """Drop candidates whose expression contains any motif in the avoid list.

    No-op when avoid_motifs is empty (fast path).

    Args:
        candidates: List of dicts with an "expression" key.
        avoid_motifs: List of motif strings to avoid.

    Returns:
        Filtered list of candidates (those not matching any avoid motif).
    """
    if not avoid_motifs:
        return candidates

    avoid_set = set(avoid_motifs)
    kept = []
    for c in candidates:
        try:
            motifs = set(extract_abstract_subtrees(c["expression"]))
        except Exception:
            # Safe default: keep candidate if extraction fails unexpectedly
            kept.append(c)
            continue
        if not (motifs & avoid_set):
            kept.append(c)
    return kept


def diversity_metric(conn: sqlite3.Connection) -> dict:
    """Compute structural diversity metric for ROADMAP criterion 4 before/after comparison.

    Returns a dict with:
        - pass_alpha_count: number of PASS alphas
        - unique_motifs: number of distinct motifs across all PASS alphas
        - top_motif: the most frequent motif string (or None if no PASS alphas)
        - top_motif_share: fraction of total motif occurrences that the top motif represents

    This function is read-only (SELECT only — no DB writes).

    Args:
        conn: SQLite connection to alpha_kb.db.

    Returns:
        Dict with pass_alpha_count, unique_motifs, top_motif, top_motif_share.
    """
    rows = conn.execute(
        "SELECT expression FROM alphas WHERE status='pass'"
    ).fetchall()

    pass_exprs = [row[0] for row in rows]

    if not pass_exprs:
        return {
            "pass_alpha_count": 0,
            "unique_motifs": 0,
            "top_motif": None,
            "top_motif_share": 0.0,
        }

    all_motifs: Counter = Counter()
    for expr in pass_exprs:
        for motif in extract_abstract_subtrees(expr):
            all_motifs[motif] += 1

    total_occurrences = sum(all_motifs.values())
    unique_motifs = len(all_motifs)

    if total_occurrences == 0:
        return {
            "pass_alpha_count": len(pass_exprs),
            "unique_motifs": 0,
            "top_motif": None,
            "top_motif_share": 0.0,
        }

    top_motif, top_count = all_motifs.most_common(1)[0]
    top_motif_share = top_count / total_occurrences

    return {
        "pass_alpha_count": len(pass_exprs),
        "unique_motifs": unique_motifs,
        "top_motif": top_motif,
        "top_motif_share": top_motif_share,
    }
