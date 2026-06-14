---
phase: 02-grounded-generation
reviewed: 2026-06-08T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - researcher.py
  - ideator.py
  - find_alphas.py
  - test_phase2.py
  - test_researcher_catalog.py
  - test_researcher_thesis.py
  - test_ideator_candidates.py
  - test_ideator_gates.py
findings:
  critical: 2
  warning: 5
  info: 4
  total: 11
status: clean
---

# Phase 02: Code Review Report

**Reviewed:** 2026-06-08
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

All eight Phase 2 source files were reviewed at standard depth. The D-02 constraint (no grade/simulate/login calls in find_alphas.py) is satisfied — confirmed by code inspection and the test suite. The grounding pipeline (catalog token intersection, validate gate, expr_exists dedup) is architecturally sound.

Two blockers were found: a potential `TypeError` crash in `gather_insights` when formatting `None` values from the DB, and a latent infinite loop in the `generate_candidates` fallback padding logic for five of the eight archetypes. Five warnings cover dead code, a wrong-expression bug in low_volatility variant generation, an unused import, fragile tests that write to the production DB, and a missing `#` guard in `to_seeds_text`. Four informational items cover code quality.

---

## Critical Issues

### CR-01: `gather_insights` crashes with `TypeError` when `fitness` or `turnover` is `NULL`

**File:** `researcher.py:184-192`

**Issue:** The query at line 177 filters `WHERE sharpe IS NOT NULL` but does NOT also require `fitness IS NOT NULL` or `turnover IS NOT NULL`. The destructure on line 184 assigns the raw DB value to `best_fitness` and `best_turnover`, then line 187-189 applies `:.2f` format to both. If either is `None` (two such rows confirmed in the live DB: `gJob1VaJ`, `88KjzRKz`), Python raises `TypeError: unsupported format character`. Those rows have `sharpe=0.0` so they are currently never the top-ranked row, but any future insert with `sharpe > 0` and `NULL fitness` will trigger the crash and break the entire pipeline.

**Fix:**
```python
# researcher.py, inside gather_insights — add NULL guards to the query and format
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
```

---

### CR-02: Infinite loop in `generate_candidates` fallback padding for five archetypes

**File:** `ideator.py:395-403`

**Issue:** The while loop at line 395 pads `all_exprs` to `min_count=4` by applying `re.sub(r'\b5\b', str(extra_w), skeleton, count=1)`. This substitution only works when the skeleton contains the digit `5` as a word-bounded literal. Five of the eight skeletons do NOT contain `\b5\b`:

- `value_garp` — no `5` in skeleton
- `quality` — no `5` in skeleton
- `growth` — no `5` in skeleton
- `low_volatility` — no `5` in skeleton (uses `60`)
- `liquidity_volume` — no `5` in skeleton (uses `20`)

For these archetypes, every `extra_w` in `[7, 15, 30, 45, 90]` produces `perturbed == skeleton`, which is already in `all_exprs`, so `all_exprs` never grows and the `while` condition never becomes false. This causes an **infinite loop**.

With the current DB the fallback is never reached (all five affected archetypes generate ≥ 5 variants from real data), but catalog drift, seed mismatch, or a DB with sparse fields will trigger it immediately.

**Fix:**
```python
# ideator.py — replace the fragile while loop with a safe bounded approach
import re as _re

_WINDOW_SUBS = [3, 7, 10, 15, 20, 30, 45, 60, 90, 120]
_DIGIT_PATTERN = _re.compile(r'\b(\d+)\b')

def _pad_to_min(all_exprs: list[str], skeleton: str, min_count: int) -> list[str]:
    """Pad all_exprs to at least min_count using window-substitution; bounded, no infinite loop."""
    if len(all_exprs) >= min_count:
        return all_exprs
    # Find the first numeric literal in the skeleton to substitute
    m = _DIGIT_PATTERN.search(skeleton)
    if m is None:
        # No digit to substitute — just return what we have (can't pad)
        return all_exprs
    for w in _WINDOW_SUBS:
        perturbed = skeleton[:m.start()] + str(w) + skeleton[m.end():]
        if perturbed not in all_exprs:
            all_exprs.append(perturbed)
        if len(all_exprs) >= min_count:
            break
    return all_exprs
```

Then replace the `while` block in `generate_candidates` with:
```python
all_exprs = _pad_to_min(all_exprs, skeleton, min_count)
```

---

## Warnings

### WR-01: `_make_low_volatility_variants` generates the skeleton as a dead duplicate

**File:** `ideator.py:249-250`

**Issue:** Lines 249–250 check `if "vector_neut" in ops:` and then append `"rank(reverse(ts_std_dev(returns, 60)))"` — which is exactly `_SKELETONS["low_volatility"]`, the first element already in `candidates`. The `_compose_expressions` dedup set silently drops it, so the `vector_neut` guard is effectively dead code that generates no unique variant. The intent was presumably to produce a `vector_neut`-wrapped expression, but `vector_neut(x, y)` requires two arguments, and no second argument is provided.

**Fix:** Either remove the dead branch entirely, or implement the intended variant (if `vector_neut` usage is desired, clarify the second argument, e.g., using a factor field):
```python
# Option A: remove the dead branch
# (delete lines 249-250)

# Option B: correct the intent if a vector_neut variant is actually wanted
# (requires determining the correct second argument per BRAIN's vector_neut(x, y) API)
```

---

### WR-02: `alt_ratios` list is built but never consumed in `_make_value_garp_variants`

**File:** `ideator.py:136-140`

**Issue:** Lines 136–140 construct `alt_ratios = [("cashflow_op", "close"), ("bookvalue_ps", "close")]` (conditionally), but the list is never iterated and never used. The function adds `cashflow_op/cap` and `bookvalue_ps/close` variants later via separate hardcoded `if` checks that duplicate the intent. The dead `alt_ratios` list implies that originally it was supposed to drive expression generation from these pairs, but that loop was never written.

**Fix:** Remove the dead `alt_ratios` accumulation (lines 136–140):
```python
def _make_value_garp_variants(ops: list[str], fields: list[str]) -> list[str]:
    """Compose value_garp candidates using fundamental ratio fields."""
    candidates = [_SKELETONS["value_garp"]]

    # mdl177 analyst model ratio
    if "mdl177_garpanalystmodel_qgp_vfpriceratio" in fields:
        ...
```

---

### WR-03: `to_seeds_text` does not enforce `#` prefix on the `header` parameter

**File:** `ideator.py:433-462`

**Issue:** The `header` parameter accepts any string. If a caller passes a value not prefixed with `#`, it is emitted as the first line of the seeds text without the comment marker. `cli.py` parses seeds with `[l.strip() for l in lines if l.strip() and not l.startswith('#')]`, so an un-prefixed header would be parsed as an expression and submitted to BRAIN. Tested: `ideator.to_seeds_text(fake, header="malicious_expression(field, 5)")` produces a line that `cli.py` would treat as a real expression.

**Fix:**
```python
def to_seeds_text(candidates: list[dict], header: Optional[str] = None) -> str:
    ...
    # Guarantee header is a comment line
    if header is not None and not header.startswith("#"):
        header = f"# {header}"
    ...
```

---

### WR-04: `test_criterion_1_grounded_note` writes to the production DB and vault with no teardown

**File:** `test_phase2.py:53-128`

**Issue:** `test_criterion_1_grounded_note` calls `find_alphas.find_alphas(db_path=DB_PATH)` where `DB_PATH = "alpha_kb.db"` — the live database. Every test run: (a) inserts a permanent row into the `runs` table, (b) creates a real `.md` file in `alpha-kb/Theses/`. There is no teardown, rollback, or fixture cleanup. Repeated test runs accumulate stale data in the production DB and filesystem. The other criterion tests (`test_criterion_2_*`, `test_criterion_3_*`) also read the same live DB via `db.init_db(DB_PATH)`.

**Fix:** Use a temporary DB and temp directory for the end-to-end criterion test:
```python
import tempfile, shutil

def test_criterion_1_grounded_note() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = os.path.join(tmpdir, "test.db")
        # Seed tmp_db from live DB (copy schema + data)
        shutil.copy(DB_PATH, tmp_db)
        # Patch THESES_DIR to write inside tmpdir
        ...
        result = find_alphas.find_alphas(db_path=tmp_db)
        ...
```

---

### WR-05: Unused `import os` in `find_alphas.py`

**File:** `find_alphas.py:17`

**Issue:** `import os` is present at line 17 but `os` is never referenced anywhere in `find_alphas.py`. All filesystem operations use `pathlib.Path` and the built-in `open()`. This is not a crash bug but it is a misleading import that obscures the actual dependency surface.

**Fix:**
```python
# Remove line 17:
# import os   <-- delete this line
```

---

## Info

### IN-01: `import re as _re` inside a `while` loop body

**File:** `ideator.py:398`

**Issue:** `import re as _re` is executed inside a nested `for` loop inside a `while` loop. Python caches module imports so this is functionally harmless (no repeated loading), but placing an import inside a loop is non-idiomatic, confusing, and obscures the module's actual static dependencies.

**Fix:** Hoist the import to the top of the file alongside the other standard-library imports:
```python
# At the top of ideator.py, alongside other imports:
import re
```
Then replace `_re.sub(...)` with `re.sub(...)`.

---

### IN-02: `hump` seed operator in `_ARCHETYPE_SEEDS["reversal"]` is unused

**File:** `researcher.py:39`

**Issue:** `"hump"` appears in `_ARCHETYPE_SEEDS["reversal"]["operators"]` and will flow into the thesis `source_operators` list (and into the Obsidian note's grounding table), but `hump` is never used in any reversal skeleton or variant expression in `ideator.py`. The thesis metadata will show `hump` as a cited operator when it does not actually appear in any generated candidate. This is a misleading grounding citation.

**Fix:** Either remove `"hump"` from the reversal seed list, or add at least one variant expression that uses it (e.g., `"rank(hump(ts_delta(close, 5), 0.05))"` if that syntax is valid per the catalog).

---

### IN-03: `VAULT_ROOT` and `THESES_DIR` are relative paths — CWD-sensitive

**File:** `find_alphas.py:32-33`

**Issue:** `VAULT_ROOT = Path("alpha-kb")` and `THESES_DIR = VAULT_ROOT / "Theses"` are relative paths. The actual directory created and the note path stored in the `runs` table will differ depending on the working directory when the script is invoked. If the script is run from a directory other than `~/quant`, the vault is created in the wrong location and the runs table stores an incorrect path.

**Fix:** Anchor the vault path to the module's location:
```python
_HERE = Path(__file__).parent
VAULT_ROOT = _HERE / "alpha-kb"
THESES_DIR = VAULT_ROOT / "Theses"
```

---

### IN-04: Invalid archetype via CLI produces an unguarded `ValueError` traceback

**File:** `find_alphas.py:477-478`

**Issue:** When `--archetype` is passed with an invalid label (e.g., `python find_alphas.py --archetype foo`), `researcher.build_thesis` raises `ValueError: Unknown archetype 'foo'` which propagates uncaught from `__main__`, printing a full traceback. The argparse `choices` mechanism could validate this cleanly at argument-parse time.

**Fix:**
```python
parser.add_argument(
    "--archetype",
    default=None,
    choices=researcher.ARCHETYPES + [None],  # or use a custom type
    help="Override archetype selection (one of the 8 taxonomy labels).",
)
```
Or more robustly, wrap the call in a try/except in `__main__` and print a user-friendly message.

---

_Reviewed: 2026-06-08_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
