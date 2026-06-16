"""handoff.py — /hunt to /bruteforce generated-template bridge.

No auth happens here. The caller passes an already-authenticated client.
No submit calls happen here. Results are candidates for human review only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable, Optional

import bruteforce
import db
import ideator
import researcher
import templates
import validate

PROMPT_VERSION = "999.1-v1"
MAX_TEMPLATE_RETRIES = 2


def _schema_error(template: dict) -> Optional[str]:
    required = ("name", "expression", "slots", "settings_archetype")
    missing = [key for key in required if key not in template]
    if missing:
        return f"missing keys: {', '.join(missing)}"
    if not isinstance(template.get("slots"), dict):
        return "slots must be a dict"
    if not isinstance(template.get("expression"), str):
        return "expression must be a string"
    return None


def validate_generated_template(conn, template: dict) -> dict:
    """Expand + validate a generated template before any sim is attempted."""
    err = _schema_error(template)
    if err:
        return {"ok": False, "n_combos": 0, "n_validated": 0, "reason": err}

    combos = templates.expand_slots(conn, template)
    if not combos:
        return {"ok": False, "n_combos": 0, "n_validated": 0, "reason": "expand_slots yielded zero combos"}

    valid = []
    first_reason = ""
    for expr, slot_vals in combos:
        ok, reason = validate.validate(conn, expr)
        if ok:
            valid.append((expr, slot_vals))
        elif not first_reason:
            first_reason = reason

    if not valid:
        return {
            "ok": False,
            "n_combos": len(combos),
            "n_validated": 0,
            "reason": first_reason or "validate yielded zero combos",
        }
    return {"ok": True, "n_combos": len(combos), "n_validated": len(valid), "reason": ""}


def register_generated_template(
    conn,
    template: dict,
    thesis: dict,
    run_id: str,
    validation: dict,
    llm_model: str = "",
) -> int:
    """Persist accepted and rejected generated-template attempts for audit."""
    return db.insert_generated_template(conn, {
        "template_name": template.get("name", "unknown"),
        "expression": template.get("expression", ""),
        "slots_json": json.dumps(template.get("slots", {}), sort_keys=True),
        "settings_archetype": template.get("settings_archetype"),
        "source_run_id": run_id,
        "source_thesis_json": json.dumps(thesis, sort_keys=True),
        "prompt_version": PROMPT_VERSION,
        "llm_model": llm_model,
        "validation_status": "accepted" if validation["ok"] else "rejected",
        "n_combos": validation["n_combos"],
        "n_validated": validation["n_validated"],
        "failure_reason": validation["reason"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def run_bruteforce_handoff(
    client,
    db_path: str = "alpha_kb.db",
    max_sims: int = 30,
    max_templates: int = 3,
    delay: int = 1,
    probe_size: int = 5,
    thesis: Optional[dict] = None,
    template_generator: Optional[Callable] = None,
    bruteforce_runner: Optional[Callable] = None,
) -> dict:
    """Run bounded generate→validate/register→bruteforce loop."""
    conn = db.init_db(db_path)
    run_id = f"handoff-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    try:
        if thesis is None:
            avoid_motifs = []
            thesis = researcher.build_thesis(conn, avoid_motifs=avoid_motifs, delay=delay)
        generator = template_generator or ideator.generate_template
        runner = bruteforce_runner or bruteforce.bruteforce

        sims_used = 0
        templates_attempted = 0
        templates_accepted = 0
        rejected_templates = 0
        feedback = None
        retry_index = 0
        best_submittable = None
        additive_ids: list = []
        stop_reason = "template_cap"

        while templates_attempted < max_templates and sims_used < max_sims:
            template = generator(
                conn,
                thesis,
                feedback=feedback,
                additivity_hint=ideator.build_additivity_hint(conn),
            )
            validation = validate_generated_template(conn, template)
            template_id = register_generated_template(conn, template, thesis, run_id, validation)
            templates_attempted += 1

            if not validation["ok"]:
                rejected_templates += 1
                feedback = validation["reason"]
                retry_index += 1
                if retry_index > MAX_TEMPLATE_RETRIES:
                    retry_index = 0
                    feedback = None
                continue

            retry_index = 0
            feedback = None
            templates_accepted += 1
            runtime_template = dict(template)
            runtime_template["generated_template_id"] = template_id

            remaining_sims = max_sims - sims_used
            result = runner(
                client,
                db_path=db_path,
                delay=delay,
                quota=1,
                probe_size=probe_size,
                generated_templates=[runtime_template],
                max_sims=remaining_sims,
            )
            sims_used += int(result.get("sims_used", 0))
            ids = list(result.get("additive_ids") or [])
            if ids:
                additive_ids.extend(ids)
                best_submittable = ids[0]
                stop_reason = "success"
                break
            if sims_used >= max_sims:
                stop_reason = "sim_budget"
                break

        if best_submittable is None and templates_attempted >= max_templates:
            stop_reason = "template_cap"
        elif best_submittable is None and sims_used >= max_sims:
            stop_reason = "sim_budget"

        return {
            "run_id": run_id,
            "best_submittable": best_submittable,
            "additive_ids": additive_ids,
            "sims_used": sims_used,
            "max_sims": max_sims,
            "templates_attempted": templates_attempted,
            "templates_accepted": templates_accepted,
            "rejected_templates": rejected_templates,
            "stop_reason": stop_reason,
            "auto_submitted": False,
        }
    finally:
        conn.close()
