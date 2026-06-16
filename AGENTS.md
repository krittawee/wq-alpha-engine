<!-- GSD:project-start source:PROJECT.md -->
## Project

**Grounded Alpha Discovery System**

A self-researching WorldQuant BRAIN alpha-generation pipeline (in `~/quant`) that
reasons over a **verified knowledge base + persistent memory** to produce *decent,
genuinely-submittable* alphas — rather than guessing like existing tools. It runs as
a Codex-orchestrated loop (research → ideate → grade → refine) for a BRAIN
participant who has ~16 manually-submitted alphas and wants to discover more
semi-autonomously. Improves on `popsukss/alpha-generator`.

**Core Value:** Produce a **decent, genuinely-submittable alpha — verified against BRAIN's own checks
(never guessed)** — while remembering every alpha tried so the system never repeats
itself and every result adds to its diversity-aware memory.

### Constraints

- **Tech stack**: `autobrain-sim` is minimal — operators/data-fields/`POST /check`/submit are all hand-written against raw endpoints — Why: SDK lacks them.
- **Auth**: periodic Persona biometric needs a human; repeated auth → 429 BIOMETRICS_THROTTLED (15–30 min). Single-shot login, **never re-auth in-loop** — Why: lockout risk.
- **Concurrency**: BRAIN sims ~2 min each, cap concurrent sims **≤3 on one shared session** — Why: BRAIN slot cap + throttle.
- **Submittability**: read each check's `result`/`limit` from BRAIN's `is.checks`; self/prod correlation via `POST /alphas/{id}/check` — Why: BRAIN is source of truth; never hardcode 1.25/0.7.
- **SDK trap**: `simulate()` `regular` param is buggy — always use the default — Why: silently drops the expression otherwise.
- **Cost**: runs inside Codex subscription (Model A); BRAIN sims free but slow — Why: time, not money, is the bottleneck.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->
## Technology Stack

Technology stack not yet documented. Will populate after codebase mapping or first phase.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.Codex/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-Codex-profile` -- do not edit manually.
<!-- GSD:profile-end -->
