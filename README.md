# Grounded Alpha Discovery System

A self-researching alpha-generation pipeline for [WorldQuant BRAIN](https://platform.worldquantbrain.com/)
that reasons over a **verified knowledge base + persistent memory** to produce *decent,
genuinely-submittable* alphas — instead of guessing like most generators.

> **Core idea:** an LLM is only allowed to be *creative about the reasoning*. The facts it
> reasons over — which operators and data-fields exist, what has already worked — come from
> deterministic reads of a verified catalog and the user's own past results. The LLM
> literally *cannot* cite an operator that isn't in the real catalog, because a local
> validator rejects it before a single simulation slot is spent.

Improves on the "spray random expressions and hope" approach (e.g. `popsukss/alpha-generator`)
by grounding every candidate in verified data and remembering every alpha tried, so the
system never repeats itself.

---

## How it works

The system is a Claude-Code-orchestrated loop with a deliberate split of responsibilities:

```
 sync ─────────► alpha_kb.db  (verified catalog + your past alphas & BRAIN scores)
                      │
                      ▼
 Phase 2: GENERATE ──► grounded thesis + candidate expressions ──► (you) grade them
        ▲                                                                │
        │                                                                ▼
 Phase 3: ITERATE ◄──── diagnose WHY they failed + mutate to fix ◄── grading results
        (planned)
```

| Phase | What it does | LLM? |
|-------|--------------|------|
| **1 — Grading Engine** | Sync BRAIN's catalog (operators/data-fields) + your existing alphas into SQLite; validate expressions locally; simulate + read **every** check limit straight from BRAIN's `is.checks` (never hardcoded); resolve correlations via `POST /check`; persist everything. | No |
| **2 — Grounded Generation** | A **Researcher** reads the verified catalog + past-result insights and assembles a grounded thesis; an **Ideator** turns it into 4–8 validate-clean, deduped candidate expressions, tagged by archetype. The `/find-alphas` command adds LLM-authored economic prose. | Yes (fenced) |
| **3 — Smart Iteration** | *(planned)* An **Editor** diagnoses which BRAIN check a graded alpha failed and proposes targeted mutations with lineage tracking + structural-diversity filters. | Yes |
| **4 — Optimization & Polish** | *(planned)* Knowledge-driven settings optimizer, decay monitor, Obsidian prose layer. | Yes |

### Design constraints (why it's built this way)

- **Submittability is verified, never guessed** — each check's `result`/`limit` is read from
  BRAIN's own `is.checks`; correlations via `POST /alphas/{id}/check`. BRAIN is the source of truth.
- **Single-shot auth** — BRAIN's periodic Persona biometric login needs a human; the pipeline
  *never* re-authenticates in-loop (repeated auth → `429 BIOMETRICS_THROTTLED` lockout).
- **Generation stops before grading** — `/find-alphas` produces candidates and stops. *You*
  control when simulations run, on your own auth timing.

---

## Usage

```bash
pip install -r requirements.txt
# create a .env with WQ_EMAIL / WQ_PASSWORD (see wq_login.py)

python sync.py                       # mirror BRAIN catalog + your alphas -> alpha_kb.db
python -m find_alphas                # generate a grounded thesis + candidates (no grading)
python cli.py seeds.txt --workers 3  # grade a seed list against BRAIN (your step, single-shot login)
```

The `/find-alphas` Claude Code command runs the full Researcher → LLM-prose → Ideator
pipeline and writes a thesis note to the local `alpha-kb/` vault.

## Tests

```bash
python -m pytest -q          # researcher / ideator / validator suites
python test_phase2.py        # asserts the Phase 2 success criteria
```

## Layout

```
sync.py validate.py grade.py cli.py db.py   # Phase 1 — grading engine
researcher.py ideator.py find_alphas.py     # Phase 2 — grounded generation
alpha-kb/                                    # Obsidian vault (thesis notes kept local)
.claude/commands/find-alphas.md             # the /find-alphas command
```

> Note: your `alpha_kb.db`, generated thesis notes, and candidate seed files are
> **gitignored** — they're your proprietary research and never leave your machine.
