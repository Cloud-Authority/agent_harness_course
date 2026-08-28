"""Promotion of recurring, verified workflow recipes into procedural skills."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .catalog import HarnessCatalog


PROMOTED_SKILL_NAME = "proven-supplier-compliance-review"


def _single_line(value: Any, *, fallback: str) -> str:
    rendered = " ".join(str(value or "").split()).strip()
    rendered = rendered.replace("[", "(").replace("]", ")")
    return rendered[:580] or fallback


def _skill_md(
    *,
    name: str,
    description: str,
    tools: list[str],
    body: str,
    recipe: Mapping[str, Any],
) -> str:
    clean_body = str(body or "").strip()
    if not clean_body:
        raise ValueError("A promoted skill requires a non-empty procedure body")
    if re.search(r"SUP-\d+|CR-\d+", clean_body, re.IGNORECASE):
        raise ValueError("Promoted skill body must be parameterised, not case-specific")
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"tools: [{', '.join(tools)}]\n"
        "---\n\n"
        "# Proven supplier-compliance review\n\n"
        "## When to use\n\n"
        "Use this skill for a supplier-compliance objective that matches the verified "
        "path from which it was distilled.\n\n"
        "## Provenance\n\n"
        f"- Source workflow recipe: `{recipe['recipe_id']}`\n"
        f"- Observed executions: {recipe['occurrences']}\n"
        f"- Successful executions: {recipe['successes']}\n"
        f"- Failed executions: {recipe['failures']}\n\n"
        "## Steps\n\n"
        f"{clean_body}\n\n"
        "## Guardrails\n\n"
        "- Retrieve tool contracts by meaning and bind only the selected subset.\n"
        "- Execute model-selected tools inside the configured sandbox.\n"
        "- Preserve evidence identifiers and deterministic policy results.\n"
        "- Keep publication behind a named human decision and verify the result outside the model.\n"
    )


class WorkflowSkillPromoter:
    """Distil eligible workflow memory and retire the raw recipe from recall."""

    def __init__(
        self,
        catalog: HarnessCatalog,
        model_provider: Any,
        *,
        min_occurrences: int = 2,
    ) -> None:
        self.catalog = catalog
        self.model_provider = model_provider
        self.min_occurrences = max(2, int(min_occurrences))

    def promote(self, recipe_id: str) -> dict[str, Any]:
        recipe = self.catalog.get_workflow(recipe_id)
        if "error" in recipe:
            return recipe
        criteria = {
            "recurs": recipe["occurrences"] >= self.min_occurrences,
            "reliable": recipe["successes"] > recipe["failures"],
            "last_run_verified": recipe["last_outcome"] == "success",
        }
        if recipe.get("promoted"):
            return {
                "status": "already_promoted",
                "skill_name": recipe.get("promoted_skill_name"),
                "source_workflow_id": recipe_id,
                "criteria": criteria,
            }
        if not all(criteria.values()):
            return {
                "status": "candidate",
                "source_workflow_id": recipe_id,
                "criteria": criteria,
                "progress": {
                    "occurrences": recipe["occurrences"],
                    "required_occurrences": self.min_occurrences,
                    "successes": recipe["successes"],
                    "failures": recipe["failures"],
                },
            }

        distilled = self.model_provider.distill_skill(recipe=recipe)
        description = _single_line(
            distilled.get("description"),
            fallback="Run the recurring verified supplier-compliance procedure.",
        )
        tools = [str(item) for item in recipe["tools_used"]]
        skill_md = _skill_md(
            name=PROMOTED_SKILL_NAME,
            description=description,
            tools=tools,
            body=str(distilled.get("body") or ""),
            recipe=recipe,
        )
        sha = self.catalog.save_skill(
            PROMOTED_SKILL_NAME,
            description,
            skill_md,
            tools,
            source_workflow_id=recipe_id,
            source_url="generated:verified-workflow-promotion",
        )
        self.catalog.mark_promoted(recipe_id, PROMOTED_SKILL_NAME)
        return {
            "status": "promoted",
            "skill_name": PROMOTED_SKILL_NAME,
            "sha": sha,
            "source_workflow_id": recipe_id,
            "criteria": criteria,
            "raw_recipe_retired_from_default_recall": True,
        }

    def status(self) -> dict[str, Any]:
        return {
            "minimum_occurrences": self.min_occurrences,
            "reliability_rule": "successes > failures",
            "verification_rule": "last outcome must be host-verified success",
            "result": "SHA-versioned SKILL.md; raw recipe retired from default recall",
        }


__all__ = ["PROMOTED_SKILL_NAME", "WorkflowSkillPromoter"]
