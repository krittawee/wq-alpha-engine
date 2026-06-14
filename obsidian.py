"""obsidian.py — Obsidian prose layer for the Alpha Discovery System.

Generates and regenerates Archetype notes, Failure-family notes, and the Decay
summary note from the live SQLite DB. All notes are deterministic and regenerated
from DB each run (D-10). No stale drift.

Public API:
    regen_archetype_notes(conn, vault_root=VAULT_ROOT) -> list[str]
    regen_failure_notes(conn, vault_root=VAULT_ROOT) -> list[str]
    write_decay_note(degraded_list, conn, vault_root=VAULT_ROOT) -> str
    regen_all(conn, vault_root=VAULT_ROOT) -> dict

OPT-03 requirement (D-08, D-09, D-10).
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import db
import researcher
from find_alphas import slugify

# ---------------------------------------------------------------------------
# Vault layout constants (mirrors find_alphas.py pattern)
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
VAULT_ROOT = _HERE / "alpha-kb"
ARCHETYPES_DIR = VAULT_ROOT / "Archetypes"
FAILURES_DIR = VAULT_ROOT / "Failures"
DECAY_NOTE = VAULT_ROOT / "Decay.md"

# ---------------------------------------------------------------------------
# Failure-family priority list (RESEARCH.md Pattern 5)
# ---------------------------------------------------------------------------

PRIORITY = [
    "CONCENTRATED_WEIGHT",
    "HIGH_TURNOVER",
    "MATCHES_COMPETITION",
    "LOW_SUB_UNIVERSE_SHARPE",
    "LOW_FITNESS",
    "LOW_SHARPE",
]

# ---------------------------------------------------------------------------
# Per-family remediation hints (brief, inline, not LLM-generated)
# ---------------------------------------------------------------------------

_REMEDIATION_HINTS = {
    "CONCENTRATED_WEIGHT": (
        "Increase truncation (e.g. 0.08→0.10) or apply group_neutralize to spread weight."
    ),
    "HIGH_TURNOVER": (
        "Increase decay or use ts_decay_linear to smooth the signal and reduce daily rebalancing."
    ),
    "MATCHES_COMPETITION": (
        "Differentiate by adding a secondary factor or using a less common datafield combination."
    ),
    "LOW_SUB_UNIVERSE_SHARPE": (
        "Try market or industry neutralization; the signal may be universe-wide rather than sub-universe-specific."
    ),
    "LOW_FITNESS": (
        "Improve signal quality: add winsorize, adjust delay, or combine with a complementary factor."
    ),
    "LOW_SHARPE": (
        "Tune decay and neutralization via /optimize; consider adding volatility scaling or rank normalization."
    ),
    "OTHER": (
        "Review the failing checks in BRAIN IS results and adjust settings accordingly."
    ),
}


# ---------------------------------------------------------------------------
# get_failure_family
# ---------------------------------------------------------------------------


def get_failure_family(alpha_id: str, conn: sqlite3.Connection) -> str:
    """Return the primary failure family name for a FAIL alpha.

    Uses PRIORITY order to pick the most critical failing check.
    Returns 'OTHER' if none of the priority checks is present.
    """
    rows = conn.execute(
        "SELECT name FROM checks WHERE alpha_id=? AND result='FAIL'",
        (alpha_id,),
    ).fetchall()
    failing = {r[0] for r in rows}
    for check in PRIORITY:
        if check in failing:
            return check
    return "OTHER"


# ---------------------------------------------------------------------------
# Internal rendering helpers
# ---------------------------------------------------------------------------


def _today_str() -> str:
    """Return today's date as YYYY-MM-DD (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _render_archetype_note(archetype: str, conn: sqlite3.Connection) -> str:
    """Build a full Obsidian Markdown note for one archetype.

    Queries PASS and NEAR alphas from the DB and populates three sections:
      - Heuristics table (PASS alphas with settings + Sharpe)
      - NEAR Alphas table (optimizer candidates)
      - PASS Alphas table (full list)

    Returns the complete Markdown string.
    """
    today = _today_str()

    # --- Query PASS/ACTIVE alphas for this archetype ---
    pass_rows = conn.execute(
        "SELECT alpha_id, decay, neutralization, truncation, sharpe, fitness "
        "FROM alphas "
        "WHERE archetype=? AND status IN ('pass', 'ACTIVE') "
        "ORDER BY sharpe DESC",
        (archetype,),
    ).fetchall()

    # --- Query NEAR alphas ---
    near_rows = conn.execute(
        "SELECT alpha_id, expression, sharpe "
        "FROM alphas "
        "WHERE archetype=? AND status='near' "
        "ORDER BY sharpe DESC",
        (archetype,),
    ).fetchall()

    # --- Query ALL alphas for this archetype (for alpha_ids in frontmatter) ---
    all_rows = conn.execute(
        "SELECT alpha_id FROM alphas WHERE archetype=?",
        (archetype,),
    ).fetchall()
    all_alpha_ids = [r[0] for r in all_rows]

    # --- Frontmatter ---
    alpha_ids_yaml = (
        "\n" + "\n".join(f"  - {aid}" for aid in all_alpha_ids)
        if all_alpha_ids
        else " []"
    )
    frontmatter_lines = [
        "---",
        f"title: {archetype} Archetype",
        f"archetype: {archetype}",
        f"updated: {today}",
        f"alpha_ids:{alpha_ids_yaml}",
        "tags: [archetype, alpha]",
        "---",
    ]
    frontmatter = "\n".join(frontmatter_lines)

    # --- Title ---
    display_title = archetype.replace("_", " ").title()
    title = f"# {display_title} Archetype"

    # --- Section: Heuristics ---
    heuristics_lines = [
        "## Heuristics",
        "",
        "What settings work for this archetype (from observed PASS alphas):",
        "",
        "| Decay | Neutralization | Truncation | Sharpe | Alpha ID |",
        "|-------|----------------|------------|--------|----------|",
    ]
    if pass_rows:
        for alpha_id, decay, neutralization, truncation, sharpe, fitness in pass_rows:
            sharpe_str = f"{sharpe:.4f}" if sharpe is not None else "—"
            heuristics_lines.append(
                f"| {decay} | {neutralization} | {truncation} | {sharpe_str} | [[{alpha_id}]] |"
            )
    else:
        heuristics_lines.append("| — | — | — | — | _no PASS alphas yet_ |")
    heuristics_section = "\n".join(heuristics_lines)

    # --- Section: NEAR Alphas ---
    near_lines = [
        "## NEAR Alphas (optimizer candidates)",
        "",
        "| Alpha ID | Expression | Sharpe |",
        "|----------|------------|--------|",
    ]
    if near_rows:
        for alpha_id, expression, sharpe in near_rows:
            sharpe_str = f"{sharpe:.4f}" if sharpe is not None else "—"
            expr_display = expression[:60] + "..." if expression and len(expression) > 60 else (expression or "—")
            near_lines.append(
                f"| [[{alpha_id}]] | `{expr_display}` | {sharpe_str} |"
            )
    else:
        near_lines.append("| — | — | — |")
    near_section = "\n".join(near_lines)

    # --- Section: PASS Alphas ---
    pass_lines = [
        "## PASS Alphas",
        "",
        "| Alpha ID | Sharpe | Fitness |",
        "|----------|--------|---------|",
    ]
    if pass_rows:
        for alpha_id, decay, neutralization, truncation, sharpe, fitness in pass_rows:
            sharpe_str = f"{sharpe:.4f}" if sharpe is not None else "—"
            fitness_str = f"{fitness:.4f}" if fitness is not None else "—"
            pass_lines.append(f"| [[{alpha_id}]] | {sharpe_str} | {fitness_str} |")
    else:
        pass_lines.append("| — | — | — |")
    pass_section = "\n".join(pass_lines)

    # --- Footer (Pitfall 5 — wikilinks are intentionally unresolved) ---
    footer = "_Alpha IDs are referenced but do not have individual notes yet._"

    # --- Assemble ---
    sections = [
        frontmatter,
        "",
        title,
        "",
        heuristics_section,
        "",
        near_section,
        "",
        pass_section,
        "",
        footer,
    ]
    return "\n".join(sections)


def _render_failure_note(
    family: str,
    alpha_ids: List[str],
    conn: sqlite3.Connection,
) -> str:
    """Build a full Obsidian Markdown note for one failure family.

    Queries expression, sharpe, archetype for each alpha_id in alpha_ids.
    Builds frontmatter + failing check table + wikilinks.

    Returns the complete Markdown string.
    """
    today = _today_str()

    # --- Query alpha details ---
    rows = []
    for alpha_id in alpha_ids:
        row = conn.execute(
            "SELECT alpha_id, expression, sharpe, archetype "
            "FROM alphas WHERE alpha_id=?",
            (alpha_id,),
        ).fetchone()
        if row:
            rows.append(row)

    # --- Frontmatter ---
    alpha_ids_yaml = (
        "\n" + "\n".join(f"  - {aid}" for aid in alpha_ids)
        if alpha_ids
        else " []"
    )
    frontmatter_lines = [
        "---",
        f"title: {family} Failure Family",
        f"family: {family}",
        f"updated: {today}",
        f"alpha_ids:{alpha_ids_yaml}",
        "tags: [failure, alpha]",
        "---",
    ]
    frontmatter = "\n".join(frontmatter_lines)

    # --- Title ---
    title = f"# Failure Family: {family}"

    # --- Section header ---
    section_header = f"## Failing Check: {family}"

    # --- Remediation hint ---
    hint = _REMEDIATION_HINTS.get(family, _REMEDIATION_HINTS["OTHER"])
    hint_line = f"**Remediation hint:** {hint}"

    # --- Table ---
    table_lines = [
        "| Alpha ID | Expression | Sharpe | Archetype |",
        "|----------|------------|--------|-----------|",
    ]
    if rows:
        for alpha_id, expression, sharpe, archetype in rows:
            sharpe_str = f"{sharpe:.4f}" if sharpe is not None else "—"
            expr_display = expression[:60] + "..." if expression and len(expression) > 60 else (expression or "—")
            arch_str = archetype or "—"
            table_lines.append(
                f"| [[{alpha_id}]] | `{expr_display}` | {sharpe_str} | {arch_str} |"
            )
    else:
        table_lines.append("| — | — | — | — |")
    table = "\n".join(table_lines)

    # --- Footer (Pitfall 5) ---
    footer = "_Alpha IDs are referenced but do not have individual notes yet._"

    # --- Assemble ---
    sections = [
        frontmatter,
        "",
        title,
        "",
        section_header,
        "",
        hint_line,
        "",
        table,
        "",
        footer,
    ]
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def regen_archetype_notes(
    conn: sqlite3.Connection,
    vault_root: Path = VAULT_ROOT,
) -> List[str]:
    """Regenerate one note per archetype from DB.

    Creates one .md file per archetype in vault_root/Archetypes/.
    After writing each note, updates alphas.note_path for all alphas
    with that archetype (two-way link DB→note per D-09).

    Returns list of written file paths (str).
    """
    archetypes_dir = vault_root / "Archetypes"
    archetypes_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for archetype in researcher.ARCHETYPES:
        note_content = _render_archetype_note(archetype, conn)
        note_filename = f"{slugify(archetype)}.md"
        note_path = archetypes_dir / note_filename
        note_path.write_text(note_content, encoding="utf-8")
        written.append(str(note_path))

        # Two-way link: update alphas.note_path for all alphas in this archetype (D-09)
        conn.execute(
            "UPDATE alphas SET note_path=? WHERE archetype=?",
            (str(note_path), archetype),
        )
        conn.commit()

    return written


def regen_failure_notes(
    conn: sqlite3.Connection,
    vault_root: Path = VAULT_ROOT,
) -> List[str]:
    """Regenerate one note per failure family from DB.

    Creates one .md file per distinct failure family in vault_root/Failures/.
    After writing each note, updates alphas.note_path for all alpha_ids
    in that family (two-way link DB→note per D-09).

    Returns list of written file paths (str).
    """
    failures_dir = vault_root / "Failures"
    failures_dir.mkdir(parents=True, exist_ok=True)

    # Query all distinct FAIL alpha_ids
    rows = conn.execute(
        "SELECT DISTINCT alpha_id FROM alphas WHERE status='fail'"
    ).fetchall()

    # Group by failure family
    families: dict = {}  # family_name -> [alpha_id]
    for (alpha_id,) in rows:
        family = get_failure_family(alpha_id, conn)
        families.setdefault(family, []).append(alpha_id)

    written = []
    for family, alpha_ids in families.items():
        note_content = _render_failure_note(family, alpha_ids, conn)
        note_filename = f"{slugify(family)}.md"
        note_path = failures_dir / note_filename
        note_path.write_text(note_content, encoding="utf-8")
        written.append(str(note_path))

        # Two-way link: update alphas.note_path for each alpha in this family (D-09)
        placeholders = ",".join("?" for _ in alpha_ids)
        conn.execute(
            f"UPDATE alphas SET note_path=? WHERE alpha_id IN ({placeholders})",
            [str(note_path)] + list(alpha_ids),
        )
        conn.commit()

    return written


def write_decay_note(
    degraded_list: list,
    conn: sqlite3.Connection,
    vault_root: Path = VAULT_ROOT,
) -> str:
    """Write (or overwrite) vault_root/Decay.md with the current decay summary.

    Single file overwritten each run (D-10 philosophy). Full history is
    preserved in checks_history. The note is a current-snapshot view.

    Parameters
    ----------
    degraded_list : list of dicts, each with keys:
        alpha_id, metric, old_value, new_value, drop_pct, checked_at
    conn          : open SQLite connection (unused for Decay.md but kept for API
                    consistency with other regen functions)
    vault_root    : Path to vault root (defaults to VAULT_ROOT constant)

    Returns
    -------
    str path to the written Decay.md file.
    """
    vault_root.mkdir(parents=True, exist_ok=True)
    decay_note_path = vault_root / "Decay.md"
    today = _today_str()

    lines = [
        "# Decay Report",
        "",
        f"_Last updated: {today}_",
        "",
        "_Alpha IDs are referenced but do not have individual notes yet._",
        "",
    ]

    if not degraded_list:
        lines.append("No degraded alphas detected in the last run.")
        lines.append("")
    else:
        # Markdown table
        lines += [
            "| Alpha ID | Metric | Old Value | New Value | Drop % | Checked At |",
            "|----------|--------|-----------|-----------|--------|------------|",
        ]
        for item in degraded_list:
            alpha_id = item.get("alpha_id", "—")
            metric = item.get("metric", "—")
            old_val = item.get("old_value")
            new_val = item.get("new_value")
            drop_pct = item.get("drop_pct")
            checked_at = item.get("checked_at", "—")

            old_str = f"{old_val:.4f}" if old_val is not None else "—"
            new_str = f"{new_val:.4f}" if new_val is not None else "—"
            drop_str = f"{drop_pct:.1%}" if drop_pct is not None else "—"

            lines.append(
                f"| [[{alpha_id}]] | {metric} | {old_str} | {new_str} | {drop_str} | {checked_at} |"
            )
        lines.append("")

    content = "\n".join(lines)
    decay_note_path.write_text(content, encoding="utf-8")
    return str(decay_note_path)


def regen_all(
    conn: sqlite3.Connection,
    vault_root: Path = VAULT_ROOT,
) -> dict:
    """Regenerate all archetype and failure notes from DB.

    Called by optimizer.run_optimize as a side-effect after variant grading.
    Does NOT call write_decay_note — the decay note is written by decay_monitor,
    not by /optimize (D-11).

    Returns
    -------
    dict with keys:
        archetype_notes : list[str] — paths of written archetype note files
        failure_notes   : list[str] — paths of written failure note files
    """
    archetype_paths = regen_archetype_notes(conn, vault_root)
    failure_paths = regen_failure_notes(conn, vault_root)
    return {
        "archetype_notes": archetype_paths,
        "failure_notes": failure_paths,
    }
