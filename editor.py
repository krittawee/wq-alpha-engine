"""editor.py — Hybrid Editor for the Alpha Discovery System.

Deterministic tier: reads the checks table, classifies each alpha
PASS/NEAR/FAIL (D-05..D-07), identifies which checks failed and by how much.
LLM tier: given the structured failure context, writes a human-readable
diagnosis and proposes 1-3 validated expression mutations.

No BRAIN API calls. No simulate/login references.
"""

import json
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

import db
import validate

# ---------------------------------------------------------------------------
# Module-level constants (verified against 03-RESEARCH.md §Code Examples)
# ---------------------------------------------------------------------------

HARD_FAIL_CHECKS = frozenset({"MATCHES_COMPETITION", "CONCENTRATED_WEIGHT"})


class EditorAuthError(RuntimeError):
    """Raised when the Claude CLI subprocess fails with an auth-related error.

    Distinct from requests.HTTPError (BRAIN 401) so callers can print an
    accurate message — "run 'claude login'" — instead of the misleading
    BRAIN re-auth guidance.
    """
    pass
EPSILON = 0.01  # floor for near-zero limits (LOW_SUB_UNIVERSE_SHARPE edge case)


# ---------------------------------------------------------------------------
# Task 1: Deterministic classification core
# ---------------------------------------------------------------------------


def classify_from_checks(alpha_id: str, conn: sqlite3.Connection) -> tuple[str, list[str]]:
    """Return ('pass'|'near'|'fail', list_of_failing_check_names).

    Algorithm (03-RESEARCH.md §NEAR Classification, D-05..D-07):
    1. Fetch all checks for alpha_id; filter out PENDING rows.
    2. If any resolved row has result='FAIL' and name in HARD_FAIL_CHECKS: return 'fail' immediately.
    3. Collect numeric_fails: result='FAIL' rows with non-None val/lim; compute gap.
    4. If no numeric_fails: return 'pass'.
    5. If <=2 numeric fails AND all gaps <=20%: return 'near'.
    6. Otherwise: return 'fail'.

    Only call for alphas that have completed Phase A IS checks.
    PENDING rows (Phase B SELF_CORRELATION/PROD_CORRELATION not yet resolved)
    are excluded from classification — they do not count against NEAR.
    SQL uses parameterized queries only (T-03-03 mitigation).
    """
    rows = conn.execute(
        "SELECT name, result, value, limit_val FROM checks WHERE alpha_id=?",
        (alpha_id,),
    ).fetchall()

    # Ignore PENDING rows (Phase B not yet complete — D-05 Pitfall 2)
    resolved = [(n, r, v, l) for n, r, v, l in rows if r != "PENDING"]

    # CR-02: if no checks rows exist at all, the alpha was never graded (e.g. a queued stub).
    # Must not classify as PASS. Distinguish from the all-PENDING case (Phase B in flight):
    # - rows is empty → never graded → 'unknown'
    # - rows all PENDING → Phase A passed, Phase B in flight → 'pass' (Pitfall 2, D-05)
    if not rows:
        return "unknown", []

    # Hard/structural fails (D-06) — check before any numeric analysis
    for name, result, val, lim in resolved:
        if result == "FAIL" and name in HARD_FAIL_CHECKS:
            return "fail", [name]

    # Numeric fails: rows with result='FAIL' and measurable value/limit
    numeric_fails = []
    for name, result, val, lim in resolved:
        if result == "FAIL" and val is not None and lim is not None:
            gap = abs(val - lim) / max(abs(lim), EPSILON)
            numeric_fails.append((name, gap))

    if not numeric_fails:
        return "pass", []

    # D-07: NEAR requires <=2 fails AND all within 20% margin
    if len(numeric_fails) <= 2 and all(gap <= 0.20 for _, gap in numeric_fails):
        return "near", [n for n, _ in numeric_fails]

    return "fail", [n for n, _ in numeric_fails]


# ---------------------------------------------------------------------------
# Task 2: LLM mutation tier with lineage
# ---------------------------------------------------------------------------


def _build_editor_context(
    alpha_row: tuple,
    checks_rows: list,
    failing_checks: list[str],
    status: str,
    avoid_motifs: Optional[list[str]] = None,
) -> str:
    """Assemble structured plain-text context for the LLM editor call.

    Contains the expression, IS metrics, classification status, each failing
    check with value/limit, and an explicit request for (a) a one-sentence
    human-readable diagnosis and (b) 1-3 mutation expressions.

    If avoid_motifs is provided, an explicit avoidance directive is appended
    to steer the LLM away from repeated structural motifs (D-15).
    """
    alpha_id, expression, sharpe, fitness, turnover, alpha_status = alpha_row

    lines = [
        "You are an alpha expression editor for WorldQuant BRAIN.",
        "",
        f"Alpha ID: {alpha_id}",
        f"Expression: {expression}",
        f"Classification: {status.upper()}",
        "",
        "IS Metrics:",
        f"  sharpe:   {sharpe}",
        f"  fitness:  {fitness}",
        f"  turnover: {turnover}",
        "",
        "Checks (resolved only, PENDING excluded):",
    ]

    for name, result, value, limit_val in checks_rows:
        if result == "FAIL":
            lines.append(f"  FAIL  {name}: value={value}, limit={limit_val}")
        else:
            lines.append(f"  {result:4s}  {name}: value={value}, limit={limit_val}")

    lines += [
        "",
        f"Failing checks: {', '.join(failing_checks) if failing_checks else 'none'}",
        "",
        "Tasks:",
        "1. Write a one-sentence human-readable diagnosis explaining WHY this alpha failed "
           "(what signal/structure causes the specific check failures).",
        "2. Propose 1-3 valid WorldQuant BRAIN FastExpr expression mutations that might "
           "pass the failing checks. Each mutation must use only known operators and data "
           "fields. List one expression per line.",
        "",
        "Respond with valid JSON only (no prose, no markdown fences), in this exact format:",
        '{"diagnosis": "<one sentence>", "mutations": ["<expr1>", "<expr2>"]}',
    ]

    if avoid_motifs:
        motifs_str = ", ".join(avoid_motifs)
        lines += [
            "",
            f"Avoid these structural motifs (Frequent Subtree Avoidance — D-15): {motifs_str}",
        ]

    return "\n".join(lines)


def _call_llm_editor(context: str) -> dict:
    """Invoke a Claude subagent via the 'claude' CLI subprocess.

    Passes the context as stdin; expects a JSON response with keys
    'diagnosis' (str) and 'mutations' (list[str]).

    Returns parsed dict or raises on subprocess error / JSON parse error.
    401-equivalent auth errors are propagated (CLAUDE.md constraint).
    """
    result = subprocess.run(
        ["claude", "--print", "--output-format", "text"],
        input=context,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        # WR-08: raise a distinct EditorAuthError for Claude CLI auth failures — NOT a
        # synthetic BRAIN 401. This prevents misleading "re-authenticate with BRAIN" guidance
        # (which could trigger 429 BIOMETRICS_THROTTLED lockout per CLAUDE.md constraints).
        if "401" in stderr or "Unauthorized" in stderr or "not authenticated" in stderr.lower():
            raise EditorAuthError(
                "Claude CLI not authenticated — run 'claude login' to fix this. "
                "(This is a Claude CLI auth issue, NOT a BRAIN session expiry.)"
            )
        raise RuntimeError(f"claude subprocess failed (rc={result.returncode}): {stderr[:200]}")

    output = result.stdout.strip()
    # Strip markdown fences if the model wraps its JSON response
    if output.startswith("```"):
        lines = output.split("\n")
        # Remove opening fence
        lines = lines[1:]
        # Remove closing fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        output = "\n".join(lines).strip()

    return json.loads(output)


def diagnose_and_mutate(
    alpha_id: str,
    conn: sqlite3.Connection,
    avoid_motifs: Optional[list[str]] = None,
) -> dict:
    """Classify, diagnose, and propose validated mutations for a graded alpha.

    1. Classify via classify_from_checks. If 'pass', return early with no mutations.
    2. Read alpha row + resolved checks from DB (parameterized, T-03-03 mitigation).
    3. Build LLM context; invoke Claude subagent for diagnosis + mutation proposals.
    4. Gate every proposed expression: validate.validate(conn, expr) + db.expr_exists(conn, expr).
       Drop invalids and duplicates silently (D-03).
    5. PRE-INSERT each valid mutation into alphas with parent_alpha_id=alpha_id,
       status='queued', created_at=utcnow, before returning. (BLOCKER 2 fix — lineage
       set at insert time, never patched afterward.)
    6. Write diagnosis string to alphas.diagnosis for the SOURCE alpha via UPDATE.

    Error handling (mirrors grade.py lines 79-88):
      401 from subprocess: re-raise immediately (never re-auth in-loop, CLAUDE.md).
      Any other exception: return gracefully with diagnosis=None, mutations=[].

    Returns dict:
      {"alpha_id": alpha_id, "status": status, "diagnosis": diagnosis_str,
       "mutations": [list of pre-inserted mutation expressions]}
    """
    import requests  # local import — only needed for 401 re-raise

    # Step 1: Classify
    status, failing_checks = classify_from_checks(alpha_id, conn)
    if status == "pass":
        return {"alpha_id": alpha_id, "status": status, "diagnosis": None, "mutations": []}

    # Step 2: Read alpha row and resolved checks
    alpha_row = conn.execute(
        "SELECT alpha_id, expression, sharpe, fitness, turnover, status "
        "FROM alphas WHERE alpha_id=?",
        (alpha_id,),
    ).fetchone()

    checks_rows = conn.execute(
        "SELECT name, result, value, limit_val FROM checks "
        "WHERE alpha_id=? AND result != 'PENDING'",
        (alpha_id,),
    ).fetchall()

    # Step 3: Build LLM context and call Claude subagent
    context = _build_editor_context(
        alpha_row, checks_rows, failing_checks, status, avoid_motifs
    )

    diagnosis_str: Optional[str] = None
    valid_mutations: list[str] = []

    try:
        llm_response = _call_llm_editor(context)
        diagnosis_str = llm_response.get("diagnosis")
        proposed_mutations = llm_response.get("mutations", [])

        # Step 4: Validation gate (D-03 — mirrors ideator.py lines 424-431)
        for expr in proposed_mutations[:3]:  # cap at 3 (D-02)
            ok, _ = validate.validate(conn, expr)
            if not ok:
                continue  # drop invalid mutations silently
            if db.expr_exists(conn, expr) is not None:
                continue  # drop duplicates silently
            valid_mutations.append(expr)

    except EditorAuthError:
        # WR-08: Claude CLI auth failure — propagate so caller can print accurate guidance
        raise
    except requests.exceptions.HTTPError as e:
        # BRAIN 401: auth expiry — propagate immediately (CLAUDE.md, T-03-02 mitigation)
        if getattr(getattr(e, "response", None), "status_code", None) == 401:
            raise
        # Other HTTP errors: graceful degrade
        return {"alpha_id": alpha_id, "status": status, "diagnosis": None, "mutations": []}
    except Exception:
        # Any other exception (subprocess failure, JSON parse error, etc.): graceful degrade
        return {"alpha_id": alpha_id, "status": status, "diagnosis": None, "mutations": []}

    # Step 5: PRE-INSERT mutation stubs before returning (BLOCKER 2 fix)
    # Generate a deterministic-looking stub alpha_id so expr_exists() can detect
    # duplicates by alpha_id. The real BRAIN alpha_id (e.g. "qXXXXXX") is assigned
    # by BRAIN after simulation; grade_one will UPDATE the row with the real alpha_id
    # once simulation completes. Using "stub-<uuid8>" prefix makes stubs identifiable.
    now = datetime.now(timezone.utc).isoformat()
    for expr in valid_mutations:
        stub_id = f"stub-{str(uuid.uuid4())[:8]}"
        db.upsert_alpha(conn, {
            "alpha_id": stub_id,
            "expression": expr,
            "parent_alpha_id": alpha_id,  # lineage — D-02, set at insert time
            "status": "queued",           # distinguishes un-graded mutations
            "created_at": now,
            # All grading fields None — filled when grade_one runs
        })

    # Step 6: Write diagnosis to the SOURCE alpha (never patched, only set here)
    if diagnosis_str is not None:
        conn.execute(
            "UPDATE alphas SET diagnosis=? WHERE alpha_id=?",
            (diagnosis_str, alpha_id),
        )
        conn.commit()

    return {
        "alpha_id": alpha_id,
        "status": status,
        "diagnosis": diagnosis_str,
        "mutations": valid_mutations,
    }
