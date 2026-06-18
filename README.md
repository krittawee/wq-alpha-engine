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

> **v1.1 — Additive Alpha Discovery:** the objective is no longer "passes BRAIN's checks" but
> "**adds to the team competition score**" — a fully-submittable alpha that is too correlated
> with your existing book can *lower* your score. Additivity is the goal; passing the checks is
> the constraint.

---

## How it works

Two decoupled tools share **one** authenticated BRAIN session (run one at a time):

```
 sync ─────────► alpha_kb.db  (verified catalog + your past alphas & BRAIN scores)
                      │
        ┌─────────────┴──────────────┐
        ▼                            ▼
 Tool A: /hunt  (LLM loop)     Tool B: /bruteforce  (AI-free)
 research→ideate→grade→        enumerate template→validate→
 editor mutate→repeat          probe→bulk-sim→additivity gate
        └─────────────┬──────────────┘
                      ▼
        additivity gate (local PnL proxy + live BRAIN correlation)
                      ▼
        /show-results  →  ranked table + BOOK_Δ (Performance Comparison)
```

| Phase | What it does | Status |
|-------|--------------|--------|
| **1 — Grading Engine** | Sync BRAIN's catalog + your alphas to SQLite; validate locally; simulate + read **every** check limit from BRAIN's `is.checks` (never hardcoded); resolve correlations via `POST /check`; persist. | ✅ |
| **2 — Grounded Generation** | A **Researcher** assembles a grounded thesis; an **Ideator** turns it into validate-clean, deduped candidates tagged by archetype. | ✅ |
| **3 — Smart Iteration** | An **Editor** diagnoses which check failed and proposes targeted mutations with lineage + structural-diversity (Frequent-Subtree-Avoidance) filters. | ✅ |
| **4 — Optimization & Polish** | Knowledge-driven settings optimizer, decay monitor, Obsidian prose layer. | ✅ |
| **5 — Delay-0 Support** | Confirmed BRAIN runs delay-0 from code (coercion-detected); `--delay` threaded end-to-end. | ✅ |
| **6 — Additivity Gate** | Local PnL-correlation proxy ranks candidates; live BRAIN correlation confirms finalists. Nothing is "submit-ready" without passing both. | ✅ |
| **7 — Brute-Force Tool (Tool B)** | Standalone, AI-free template enumeration → validate → probe → bulk-sim → additivity gate. Runs even when the LLM quota is exhausted. | ✅ |
| **8–9 — Evolve /hunt, /iterate decorrelate** | Additivity-ranked selection; decorrelate mode for an already-passing alpha. | planned |

### Design constraints (why it's built this way)

- **Additivity is the objective** — a submit recommendation must pass the additivity gate, not just IS checks. Local PnL-correlation proxy first, live BRAIN `POST /alphas/{id}/check` to confirm.
- **Submittability is verified, never guessed** — each check's `result`/`limit` is read from BRAIN's own `is.checks`. BRAIN is the source of truth.
- **Single-shot auth** — BRAIN's periodic Persona biometric needs a human; the pipeline *never* re-authenticates in-loop (repeated auth → `429 BIOMETRICS_THROTTLED` lockout). The first login is interactive; the session caches (~4h) and later runs reuse it.
- **Concurrency ≤3** simulations on the one shared session.
- **Submission stays manual** — `POST /alphas/{id}/submit` is out of scope by design (avoid bad/duplicate submits).

---

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# create a .env with WQ_EMAIL / WQ_PASSWORD (see wq_login.py)

python sync.py                 # first login (interactive biometric) + mirror catalog/alphas -> alpha_kb.db
# delay-0 catalog (optional): python -c "import db,sync;from wq_login import login;c=login();conn=db.init_db('alpha_kb.db');sync.sync_datafields(c,conn,delay=0)"
```

## Skills (Claude Code slash commands)

| Skill | Purpose |
|-------|---------|
| `/hunt` | Autonomous LLM discovery loop (Tool A). `--delay`, `--max-sims`, `--max-depth`. |
| `/bruteforce` | AI-free template sweep (Tool B). `--delay`, `--quota`, `--probe-size`, `--templates`. |
| `/iterate` | Diagnose & mutate NEAR/FAIL alphas with the Editor. |
| `/find-alphas` | Grounded thesis + candidates only (no grading). |
| `/optimize` | Settings optimizer + Obsidian note regen for NEAR alphas. |
| `/decay` | Flag alphas whose metrics degrade over time. |
| `/show-results` | Ranked results table + **BOOK_Δ** (BRAIN Performance Comparison: before/after team-score change). `--live` fetches the real number. |

Or run the modules directly, e.g. `python hunt.py --max-sims 30`, `python bruteforce.py --delay 1 --quota 5`,
`python cli.py seeds.txt --workers 3`, `python show_results.py --live`.

## Tests

```bash
python -m pytest -q --ignore=test_sim.py   # offline suites (test_sim.py needs a live BRAIN login)
```

> Catalog-dependent tests (researcher/ideator) pass only after `python sync.py` has populated `alpha_kb.db`.

## Layout

```
sync.py validate.py grade.py cli.py db.py        # Phase 1 — grading engine
researcher.py ideator.py find_alphas.py          # Phase 2 — grounded generation
editor.py selfcorr.py fsa.py hunt.py             # Phase 3 — smart iteration / Tool A
optimizer.py optimize.py decay_monitor.py obsidian.py   # Phase 4 — optimization & polish
probe_delay.py delay0_candidates.py verify_delay0.py    # Phase 5 — delay-0 support
additivity.py                                    # Phase 6 — additivity gate
templates.py bruteforce.py                       # Phase 7 — brute-force tool (Tool B)
handoff.py                                        # hunt→bruteforce template bridge (source only)
show_results.py                                  # results viewer + Performance Comparison (BOOK_Δ)
alpha-kb/                                         # Obsidian vault (thesis notes kept local)
.claude/commands/*.md                            # the slash-command skills
```

> Note: your `alpha_kb.db`, PnL cache, generated thesis notes, seed/candidate files, and run
> logs are **gitignored** — they're your proprietary research and never leave your machine.
