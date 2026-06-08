"""find_alphas.py — Orchestrator for the /find-alphas Claude Code command.

Runs the full Researcher -> Ideator pipeline, emits a grounded Obsidian thesis
note to alpha-kb/Theses/, and writes one row to the runs table per invocation.

STOPS at candidates — does NOT call grade/simulate/login (LOCKED D-02).

Public API:
    find_alphas(db_path, archetype, prose) -> dict
    render_note(thesis, candidates, run_id, prose) -> str
    write_runs_row(conn, run_id, thesis, note_path, candidate_count) -> None
    slugify(text) -> str
"""

import argparse
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import db
import ideator
import researcher

# ---------------------------------------------------------------------------
# Vault constants (D-05 LOCKED)
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
VAULT_ROOT = _HERE / "alpha-kb"
THESES_DIR = VAULT_ROOT / "Theses"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def slugify(text: str, max_len: int = 40) -> str:
    """Convert a text string to a lowercase slug for use in filenames.

    Strips non-alphanumeric characters (except hyphens), collapses runs of
    whitespace/underscores/hyphens to single hyphens, and truncates at max_len.

    T-02-09: strips path-traversal characters; archetype is constrained to the
    8-label set (all alnum-safe); date is ISO. Combined, the note filename cannot
    traverse directories.
    """
    # Lowercase
    slug = text.lower()
    # Replace whitespace and underscores with hyphens
    slug = re.sub(r"[\s_]+", "-", slug)
    # Remove any character that is not alphanumeric or hyphen
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    # Collapse consecutive hyphens
    slug = re.sub(r"-{2,}", "-", slug)
    # Strip leading/trailing hyphens
    slug = slug.strip("-")
    # Truncate
    return slug[:max_len]


def _build_frontmatter(thesis: dict, candidates: list, run_id: str, date_str: str) -> str:
    """Build the YAML frontmatter block for the thesis note."""
    archetype = thesis.get("archetype", "unknown")
    region = thesis.get("region", "USA")
    universe = thesis.get("universe", "TOP3000")
    delay = thesis.get("delay", 1)
    source_operators = thesis.get("source_operators", [])
    source_datafields = thesis.get("source_datafields", [])
    cited_alpha_ids = thesis.get("cited_alpha_ids", [])
    cited_insights = thesis.get("cited_insights", [])
    candidate_count = len(candidates)

    def _yaml_list(items: list, indent: int = 2) -> str:
        """Format a list as inline YAML or block list."""
        if not items:
            return "[]"
        pad = " " * indent
        lines = [f"- {item}" for item in items]
        return "\n" + "\n".join(pad + line for line in lines)

    # cited_insights: each insight may span multiple lines — wrap in quotes
    insights_lines = []
    for ins in cited_insights:
        # Escape any double quotes inside the insight text
        safe = ins.replace('"', '\\"')
        # Truncate very long insights for readability (first 200 chars)
        if len(safe) > 200:
            safe = safe[:197] + "..."
        insights_lines.append(f'  - "{safe}"')
    insights_yaml = (
        "\n" + "\n".join(insights_lines) if insights_lines else "  []"
    )

    ops_yaml = _yaml_list(source_operators)
    fields_yaml = _yaml_list(source_datafields)
    alpha_ids_yaml = _yaml_list(cited_alpha_ids)

    # Derive a short thesis title from archetype + run_id
    title = f"{archetype.replace('_', ' ').title()} Alpha Thesis ({run_id})"

    lines = [
        "---",
        f"title: {title}",
        f"date: {date_str}",
        "status: proposed",
        f"archetype: {archetype}",
        f"run_id: {run_id}",
        f"region: {region}",
        f"universe: {universe}",
        f"delay: {delay}",
        f"source_operators:{ops_yaml}",
        f"source_datafields:{fields_yaml}",
        f"cited_alpha_ids:{alpha_ids_yaml}",
        f"cited_insights:{insights_yaml}",
        f"candidate_count: {candidate_count}",
        f"tags: [thesis, alpha, {archetype}]",
        "---",
    ]
    return "\n".join(lines)


def _build_grounding_tables(thesis: dict) -> str:
    """Build the ## Grounding section: markdown tables of cited operators and fields."""
    source_operators = thesis.get("source_operators", [])
    source_datafields = thesis.get("source_datafields", [])

    lines = ["## Grounding: operators & fields cited", ""]
    lines.append(
        "_Every token confirmed in the synced catalog; `validate.py` rejects otherwise._"
    )
    lines.append("")

    # Operators table
    lines.append("### Operators")
    lines.append("")
    lines.append("| Operator | Category | Definition |")
    lines.append("|----------|----------|------------|")
    for op in source_operators:
        lines.append(f"| `{op}` | — | — |")
    if not source_operators:
        lines.append("| _(none)_ | — | — |")
    lines.append("")

    # Fields table
    lines.append("### Data fields")
    lines.append("")
    lines.append("| Field ID | Description | Dataset | Type |")
    lines.append("|----------|-------------|---------|------|")
    for fid in source_datafields:
        lines.append(f"| `{fid}` | — | — | — |")
    if not source_datafields:
        lines.append("| _(none)_ | — | — | — |")
    lines.append("")

    return "\n".join(lines)


def _build_insight_section(thesis: dict) -> str:
    """Build the ## Past-result insight cited section with wikilinks."""
    cited_alpha_ids = thesis.get("cited_alpha_ids", [])
    cited_insights = thesis.get("cited_insights", [])

    lines = ["## Past-result insight cited", ""]

    if cited_insights:
        for i, ins in enumerate(cited_insights):
            lines.append(f"**Insight {i + 1}:** {ins}")
            lines.append("")
    else:
        lines.append("_No past-alpha insights available._")
        lines.append("")

    if cited_alpha_ids:
        wikilinks = " ".join(f"[[{aid}]]" for aid in cited_alpha_ids)
        lines.append(f"Cited alphas: {wikilinks}")
    lines.append("")

    return "\n".join(lines)


def _build_candidate_section(candidates: list) -> str:
    """Build the ## Candidate expressions section with seeds.txt block + dedup table."""
    lines = ["## Candidate expressions", ""]

    # seeds.txt-format fenced block using only queueable candidates
    q = ideator.queueable(candidates)
    seeds_text = ideator.to_seeds_text(candidates)
    lines.append("```text")
    lines.append(seeds_text)
    lines.append("```")
    lines.append("")

    # Dedup table: ALL candidates (including invalid/dupes, for transparency)
    lines.append("| # | expression | archetype | dedupe |")
    lines.append("|---|------------|-----------|--------|")
    for i, c in enumerate(candidates, start=1):
        expr = c["expression"]
        arch = c["archetype"]
        dedup_id = c.get("dedup_alpha_id")
        valid = c.get("valid", True)

        if dedup_id:
            dedupe_cell = f"DUPE → {dedup_id}"
        elif not valid:
            reason = c.get("validation_reason", "invalid")
            dedupe_cell = f"INVALID: {reason}"
        else:
            dedupe_cell = "novel"

        # Truncate long expressions for readability in table
        display_expr = expr if len(expr) <= 80 else expr[:77] + "..."
        lines.append(f"| {i} | `{display_expr}` | {arch} | {dedupe_cell} |")

    lines.append("")
    lines.append(f"**Queueable:** {len(q)} of {len(candidates)} candidates are valid and novel.")
    lines.append("")

    return "\n".join(lines)


def render_note(
    thesis: dict,
    candidates: list,
    run_id: str,
    prose: Optional[dict] = None,
) -> str:
    """Render a complete Obsidian thesis note as a Markdown string.

    Parameters
    ----------
    thesis:     Dict from researcher.build_thesis.
    candidates: List of candidate dicts from ideator.generate_candidates.
    run_id:     8-char UUID string (FK to runs.run_id).
    prose:      Optional dict with keys:
                  'thesis_prose'    — LLM-authored one-paragraph thesis claim (D-03)
                  'rationale_prose' — LLM-authored economic rationale (D-03)
                If None, placeholder text is inserted (clearly marked).

    Returns
    -------
    Full Markdown string for the thesis note. Write this to
    alpha-kb/Theses/YYYY-MM-DD-<archetype>-<slug>.md.

    No grade/simulate/login calls are made here (D-02).
    """
    archetype = thesis.get("archetype", "unknown")
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # --- Frontmatter ---
    frontmatter = _build_frontmatter(thesis, candidates, run_id, date_str)

    # --- Title ---
    title_text = f"{archetype.replace('_', ' ').title()} Alpha Thesis ({run_id})"
    title_line = f"# {title_text}"

    # --- Thesis (LLM prose or placeholder) ---
    if prose and prose.get("thesis_prose"):
        thesis_prose = prose["thesis_prose"]
    else:
        thesis_prose = (
            "_[PLACEHOLDER — to be authored by the /find-alphas Claude agent step (D-03). "
            "Write a one-paragraph claim: signal, horizon, edge. "
            "Ground it in the cited operators, fields, and SQLite insights above.]_"
        )
    thesis_section = f"## Thesis\n\n{thesis_prose}\n"

    # --- Economic rationale (LLM prose or placeholder) ---
    if prose and prose.get("rationale_prose"):
        rationale_prose = prose["rationale_prose"]
    else:
        rationale_prose = (
            "_[PLACEHOLDER — to be authored by the /find-alphas Claude agent step (D-03). "
            "Explain in 2-4 sentences why this signal has a real economic mechanism: "
            "who is on the wrong side of the trade, why does it persist?]_"
        )
    rationale_section = f"## Economic rationale\n\n{rationale_prose}\n"

    # --- Grounding tables ---
    grounding_section = _build_grounding_tables(thesis)

    # --- Past-result insight ---
    insight_section = _build_insight_section(thesis)

    # --- Candidate expressions ---
    candidate_section = _build_candidate_section(candidates)

    # --- Next steps ---
    next_steps_section = "\n".join([
        "## Next steps",
        "",
        "- [ ] Review candidates in the table above and select queueable set",
        "- [ ] Copy seeds.txt block to a file and run: `python cli.py <seeds-file> --workers 3`",
        "- [ ] Update `status: proposed` → `status: grading` when grading starts",
        "- [ ] After grading: update `status: graded`; link graded alpha_ids back to this note",
        "- [ ] If any candidates fail all BRAIN checks: move note to `alpha-kb/Failures/`",
        "- [ ] Hand high-margin survivors to Phase 4 Settings Optimizer",
        "",
    ])

    # Assemble in template order (02-GROUNDING.md §Obsidian thesis-note template)
    sections = [
        frontmatter,
        "",
        title_line,
        "",
        thesis_section,
        rationale_section,
        grounding_section,
        insight_section,
        candidate_section,
        next_steps_section,
    ]
    return "\n".join(sections)


def write_runs_row(
    conn: sqlite3.Connection,
    run_id: str,
    thesis: dict,
    note_path: str,
    candidate_count: int,
) -> None:
    """Insert one row into the runs table (D-06).

    Schema (db.py:37-40):
        runs(run_id TEXT PK, thesis TEXT, started_at TEXT,
             iterations INTEGER, num_pass INTEGER, notes TEXT)

    Phase 2 write contract:
        run_id      — uuid4()[:8]
        thesis      — archetype label (one-line identifier for this run)
        started_at  — ISO UTC timestamp
        iterations  — number of candidates generated (not graded; num_pass is NULL)
        num_pass    — NULL (not graded yet; the grader fills this later)
        notes       — relative path to the emitted thesis note (for linking loop)

    T-02-11: only the confirmed db.py:37-40 schema columns are written.
    Uses a parameterized INSERT to prevent injection (T-02-10 mitigation).
    """
    archetype = thesis.get("archetype", "unknown")
    started_at = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT OR REPLACE INTO runs (run_id, thesis, started_at, iterations, num_pass, notes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, archetype, started_at, candidate_count, None, note_path),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Task 2 — find_alphas() orchestrator
# ---------------------------------------------------------------------------


def find_alphas(
    db_path: str = "alpha_kb.db",
    archetype: Optional[str] = None,
    prose: Optional[dict] = None,
) -> dict:
    """Run the full Researcher -> Ideator -> note -> runs pipeline.

    Parameters
    ----------
    db_path:   Path to the SQLite database. Defaults to "alpha_kb.db".
    archetype: Optional archetype override (one of the 8 taxonomy labels).
               If None, researcher.select_archetype() chooses deterministically.
    prose:     Optional dict with LLM-authored prose:
                 'thesis_prose'    — one-paragraph thesis claim (D-03)
                 'rationale_prose' — economic rationale (D-03)
               Supplied by the /find-alphas command's Claude agent step.
               If None, render_note inserts clearly-marked placeholders.

    Returns
    -------
    Dict with:
        run_id          — 8-char UUID identifying this run
        note_path       — relative path to the emitted thesis note
        archetype       — archetype label used
        candidate_count — total candidates generated (valid + invalid + dupes)
        queueable_count — candidates that are valid AND novel (queueable for grading)

    STOPS HERE — does NOT call grade/simulate/login (D-02 LOCKED).
    Grading is run separately by the human: `python cli.py <seeds-file> --workers 3`
    """
    # 1. Open DB connection
    conn = db.init_db(db_path)

    try:
        # 2. Build grounded thesis (deterministic archetype selection + catalog reads)
        thesis = researcher.build_thesis(conn, archetype=archetype)

        # 3. Generate candidates (validate gate + dedup via expr_exists)
        candidates = ideator.generate_candidates(conn, thesis)

        # 4. Generate run_id (uuid4 trimmed to 8 chars — matches cli.py convention)
        run_id = str(uuid.uuid4())[:8]

        # 5. Compute note path: alpha-kb/Theses/YYYY-MM-DD-<archetype>-<slug>.md
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        chosen_archetype = thesis["archetype"]
        # Slug derived from the archetype (deterministic, path-safe via slugify)
        arch_slug = slugify(chosen_archetype)
        # Add run_id suffix to guarantee uniqueness within same day + archetype
        note_filename = f"{date_str}-{arch_slug}-{run_id}.md"
        note_path = str(THESES_DIR / note_filename)

        # 6. Render the thesis note
        note_content = render_note(thesis, candidates, run_id, prose=prose)

        # 7. Write the note file (ensure THESES_DIR exists)
        THESES_DIR.mkdir(parents=True, exist_ok=True)
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(note_content)

        # 8. Write the runs row (D-06)
        write_runs_row(conn, run_id, thesis, note_path, len(candidates))

        # 9. Compute queueable count
        q = ideator.queueable(candidates)
        queueable_count = len(q)

        result = {
            "run_id": run_id,
            "note_path": note_path,
            "archetype": chosen_archetype,
            "candidate_count": len(candidates),
            "queueable_count": queueable_count,
        }

    finally:
        conn.close()

    # 10. Human handoff — print summary (D-02: stops here, no grading)
    print(f"\n--- /find-alphas complete ---")
    print(f"  run_id:          {result['run_id']}")
    print(f"  archetype:       {result['archetype']}")
    print(f"  candidates:      {result['candidate_count']} total, {result['queueable_count']} queueable")
    print(f"  thesis note:     {result['note_path']}")
    print(f"\nReview the note above, then grade the queueable candidates separately:")
    print(f"  python cli.py <seeds-file> --workers 3")
    print(f"  (lift the seeds.txt block from the note, or write it to a file)")
    print(f"\nDO NOT run grading from /find-alphas — that is a separate human step (D-02).\n")

    return result


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "find_alphas.py — /find-alphas orchestrator. "
            "Runs Researcher -> Ideator, emits an Obsidian thesis note, "
            "and writes a runs row. STOPS before grading (D-02)."
        )
    )
    parser.add_argument(
        "--archetype",
        default=None,
        choices=researcher.ARCHETYPES,
        help="Override archetype selection (one of: %(choices)s). "
             "If not set, researcher.select_archetype() chooses deterministically.",
    )
    parser.add_argument(
        "--db",
        default="alpha_kb.db",
        help="Path to the SQLite DB (default: alpha_kb.db).",
    )
    args = parser.parse_args()

    result = find_alphas(db_path=args.db, archetype=args.archetype)
    print(f"Done: {result}")
