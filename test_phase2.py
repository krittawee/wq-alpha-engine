"""test_phase2.py — End-to-end criterion tests for Phase 2: Grounded Generation.

Machine-verifies all 3 ROADMAP Phase 2 success criteria:

Criterion 1: /find-alphas produces a thesis note citing real catalog
             operators/fields + >=1 SQLite insight.
Criterion 2: The local validator rejects ZERO Ideator queueable outputs
             for unknown tokens.
Criterion 3: Every generated candidate is archetype-tagged (in the 8-label
             set) and confirmed absent from alphas.expression via db.expr_exists
             before queueing.

Usage:
    python test_phase2.py         # runs all 3 tests; exits 0 on pass
    pytest test_phase2.py -v      # pytest-compatible

CRITICAL: This file makes ZERO grade/simulate/login calls (D-02 LOCKED).
"""

import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import db
import find_alphas
import ideator
import researcher
import validate

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

DB_PATH = "alpha_kb.db"

ARCHETYPE_SET = frozenset([
    "reversal",
    "momentum",
    "value_garp",
    "quality",
    "growth",
    "low_volatility",
    "liquidity_volume",
    "sentiment_event",
])


# ---------------------------------------------------------------------------
# Criterion 1: Grounded thesis note cites real catalog tokens + >=1 insight
# ---------------------------------------------------------------------------


def test_criterion_1_grounded_note() -> None:
    """Criterion 1: Note cites real catalog operators/fields + >=1 SQLite insight.

    Steps:
    1. Run find_alphas.find_alphas() to emit a fresh note (using temp DB + temp vault).
    2. Read the emitted note.
    3. Parse source_operators and source_datafields from YAML frontmatter.
    4. Assert every token is present in the live catalog (re-query DB).
    5. Assert cited_alpha_ids is non-empty (>=1 real alpha cited).
    6. Assert the note body contains >=1 wikilink referencing a cited alpha_id.

    Uses a temp DB copy and temp vault directory so the test does NOT mutate
    production state (WR-04): no permanent rows in the production runs table and
    no stale .md files in alpha-kb/Theses/.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Temp DB: copy live DB so catalog + alphas data is available, but
        # any rows written by this test stay inside tmpdir.
        tmp_db = os.path.join(tmpdir, "test.db")
        shutil.copy(DB_PATH, tmp_db)

        # Temp vault: patch find_alphas module-level THESES_DIR so notes go
        # into tmpdir, not the real alpha-kb/Theses/.
        tmp_theses_dir = Path(tmpdir) / "Theses"
        tmp_theses_dir.mkdir(parents=True, exist_ok=True)
        orig_theses_dir = find_alphas.THESES_DIR
        find_alphas.THESES_DIR = tmp_theses_dir
        try:
            # Step 1: Run the pipeline to emit a fresh thesis note
            result = find_alphas.find_alphas(db_path=tmp_db)
            note_path = result["note_path"]

            # Step 2: Read the emitted note
            assert os.path.isfile(note_path), (
                f"Criterion 1 FAIL: note file not found at {note_path!r}"
            )
            with open(note_path, encoding="utf-8") as f:
                note_content = f.read()

            assert len(note_content) > 100, (
                f"Criterion 1 FAIL: note is suspiciously short ({len(note_content)} chars)"
            )

            # Step 3: Parse YAML frontmatter (stdlib only — no PyYAML required)
            fm_match = re.match(r"^---\n(.*?)\n---", note_content, re.DOTALL)
            assert fm_match, "Criterion 1 FAIL: note has no YAML frontmatter block"
            fm_text = fm_match.group(1)

            source_operators = _parse_yaml_list(fm_text, "source_operators")
            source_datafields = _parse_yaml_list(fm_text, "source_datafields")
            cited_alpha_ids = _parse_yaml_list(fm_text, "cited_alpha_ids")

            # Step 4a: Assert every source_operator is in live operators table
            # (re-query from the temp DB which mirrors the live catalog)
            conn = db.init_db(tmp_db)
            try:
                live_op_names = {
                    row[0]
                    for row in conn.execute("SELECT name FROM operators").fetchall()
                }
                for op in source_operators:
                    assert op in live_op_names, (
                        f"Criterion 1 FAIL: source_operator {op!r} not in live operators catalog"
                    )

                # Step 4b: Assert every source_datafield is in live datafields table
                live_field_ids = {
                    row[0]
                    for row in conn.execute("SELECT id FROM datafields").fetchall()
                }
                for fid in source_datafields:
                    assert fid in live_field_ids, (
                        f"Criterion 1 FAIL: source_datafield {fid!r} not in live datafields catalog"
                    )
            finally:
                conn.close()

            # Step 5: Assert at least one cited alpha_id (>=1 SQLite insight)
            assert len(cited_alpha_ids) >= 1, (
                "Criterion 1 FAIL: cited_alpha_ids is empty — note cites no past alpha insights"
            )

            # Step 6: Assert the note body references cited alphas as wikilinks
            # The body is the content after the closing --- of the frontmatter
            body = note_content[fm_match.end():]
            wikilink_ids = re.findall(r"\[\[([^\]]+)\]\]", body)
            cited_and_linked = [aid for aid in cited_alpha_ids if aid in wikilink_ids]
            assert len(cited_and_linked) >= 1, (
                f"Criterion 1 FAIL: no cited_alpha_id appears as a [[wikilink]] in the note body. "
                f"cited_alpha_ids={cited_alpha_ids}, wikilinks_found={wikilink_ids}"
            )

        finally:
            # Restore original module-level THESES_DIR regardless of outcome
            find_alphas.THESES_DIR = orig_theses_dir

    print("PASS: test_criterion_1_grounded_note")


# ---------------------------------------------------------------------------
# Criterion 2: Validator rejects ZERO queueable Ideator outputs
# ---------------------------------------------------------------------------


def test_criterion_2_validator_rejects_zero() -> None:
    """Criterion 2: validate.validate returns True for EVERY queueable candidate.

    Steps:
    1. Build a thesis via researcher.build_thesis.
    2. Generate candidates via ideator.generate_candidates.
    3. Take the queueable subset via ideator.queueable.
    4. Re-run validate.validate on EVERY queueable candidate.
    5. Assert ALL return (True, '').

    Queueable candidates are by definition valid (queueable() filters by valid==True),
    so this test double-checks by re-running validate independently against the live
    catalog — confirming the Ideator never generates unknown-token expressions.
    """
    conn = db.init_db(DB_PATH)
    try:
        thesis = researcher.build_thesis(conn)
        candidates = ideator.generate_candidates(conn, thesis)
        q = ideator.queueable(candidates)

        assert len(q) >= 1, (
            "Criterion 2 FAIL: queueable set is empty — nothing to assert zero rejections on. "
            "This suggests all candidates failed validation or dedup, which itself violates criterion 2."
        )

        failures = []
        for c in q:
            valid, reason = validate.validate(conn, c["expression"])
            if not valid:
                failures.append((c["expression"], reason))

        assert len(failures) == 0, (
            f"Criterion 2 FAIL: {len(failures)} queueable candidate(s) rejected by validate:\n"
            + "\n".join(f"  REJECTED: {expr!r} — {reason}" for expr, reason in failures)
        )

    finally:
        conn.close()

    print(f"PASS: test_criterion_2_validator_rejects_zero")


# ---------------------------------------------------------------------------
# Criterion 3: Every queueable candidate is archetype-tagged + novel
# ---------------------------------------------------------------------------


def test_criterion_3_tagged_and_novel() -> None:
    """Criterion 3: Every queueable candidate is archetype-tagged + expr_exists=None.

    Steps:
    1. Build a thesis and generate candidates.
    2. Take the queueable subset.
    3. Assert every queueable candidate has archetype in ARCHETYPE_SET (non-empty tag).
    4. Assert db.expr_exists returns None for every queueable candidate (novel, not in DB).
    """
    conn = db.init_db(DB_PATH)
    try:
        thesis = researcher.build_thesis(conn)
        candidates = ideator.generate_candidates(conn, thesis)
        q = ideator.queueable(candidates)

        assert len(q) >= 1, (
            "Criterion 3 FAIL: queueable set is empty — nothing to assert on. "
            "Check ideator and validator outputs."
        )

        arch_failures = []
        dedup_failures = []

        for c in q:
            # Archetype tag check
            arch = c.get("archetype", "")
            if not arch or arch not in ARCHETYPE_SET:
                arch_failures.append((c["expression"], arch))

            # Novel (not in DB) check — re-run expr_exists independently
            existing_id = db.expr_exists(conn, c["expression"])
            if existing_id is not None:
                dedup_failures.append((c["expression"], existing_id))

        assert len(arch_failures) == 0, (
            f"Criterion 3 FAIL: {len(arch_failures)} queueable candidate(s) have missing/invalid archetype:\n"
            + "\n".join(f"  BAD ARCH: {expr!r} — got {arch!r}" for expr, arch in arch_failures)
        )

        assert len(dedup_failures) == 0, (
            f"Criterion 3 FAIL: {len(dedup_failures)} queueable candidate(s) already exist in alphas table:\n"
            + "\n".join(f"  DUPE: {expr!r} — matches alpha_id {aid!r}" for expr, aid in dedup_failures)
        )

    finally:
        conn.close()

    print(f"PASS: test_criterion_3_tagged_and_novel")


# ---------------------------------------------------------------------------
# Stdlib-only YAML list parser (avoids PyYAML dependency)
# ---------------------------------------------------------------------------


def _parse_yaml_list(fm_text: str, key: str) -> list:
    """Parse a YAML block-list value from raw frontmatter text.

    Handles two formats:
      key: []                  -> returns []
      key:
        - item1
        - item2                -> returns ['item1', 'item2']

    No PyYAML required. Sufficient for the controlled frontmatter format
    emitted by find_alphas.render_note.
    """
    # Inline empty list
    inline_empty = re.search(rf"^{re.escape(key)}:\s*\[\]\s*$", fm_text, re.MULTILINE)
    if inline_empty:
        return []

    # Block list: find key, then collect all "  - value" lines until the next key or EOF
    block_match = re.search(
        rf"^{re.escape(key)}:\s*\n((?:[ \t]+-[^\n]*\n?)*)",
        fm_text,
        re.MULTILINE,
    )
    if not block_match:
        return []

    raw_block = block_match.group(1)
    items = []
    for line in raw_block.splitlines():
        line = line.strip()
        if line.startswith("- "):
            value = line[2:].strip()
            # Strip surrounding quotes if present (cited_insights are quoted)
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            items.append(value)

    return items


# ---------------------------------------------------------------------------
# __main__ runner — exits 0 on all pass, 1 on any failure
# ---------------------------------------------------------------------------


def _run_all() -> int:
    tests = [
        test_criterion_1_grounded_note,
        test_criterion_2_validator_rejects_zero,
        test_criterion_3_tagged_and_novel,
    ]
    passed = 0
    failed = 0

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as exc:
            print(f"FAIL: {test_fn.__name__}")
            print(f"  {exc}")
            failed += 1
        except Exception as exc:
            print(f"ERROR: {test_fn.__name__} — unexpected exception")
            print(f"  {type(exc).__name__}: {exc}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Phase 2 criterion suite: {passed} passed, {failed} failed")
    print(f"{'='*50}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_all())
