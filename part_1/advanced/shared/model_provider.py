"""Report-drafting provider seam for the durable compliance workflow."""

from __future__ import annotations

import json
from typing import Any, Mapping

from .config import AdvancedSettings, settings as default_settings
from .persistence import json_safe


def _authoritative_findings(source_case: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for control in source_case["controls"]:
        severity = (
            "blocking"
            if control["status"] == "expired"
            else "material"
            if control["status"] == "open"
            else "clear"
        )
        findings.append(
            {
                "control_id": control["control_id"],
                "evidence_id": control["evidence_id"],
                "status": control["status"],
                "severity": severity,
            }
        )
    return findings


def _ground_report(
    candidate: Mapping[str, Any],
    *,
    source_case: Mapping[str, Any],
    context: Mapping[str, Any],
    freshness_result: Mapping[str, Any] | None = None,
    sanctions_result: Mapping[str, Any] | None = None,
    risk_assessment: Mapping[str, Any] | None = None,
    remediation_plan: Mapping[str, Any] | None = None,
    loaded_skills: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reject ungrounded model output and restore authoritative identifiers."""

    expected_findings = _authoritative_findings(source_case)
    candidate_findings = json_safe(candidate.get("findings") or [])
    if candidate_findings != expected_findings:
        raise ValueError(
            "Draft provider changed an evidence identifier, control status, or policy severity"
        )
    expected_risk = str((risk_assessment or {}).get("route") or (
        "blocked_pending_remediation"
        if any(item["severity"] == "blocking" for item in expected_findings)
        else "review"
    ))
    if candidate.get("risk") != expected_risk:
        raise ValueError("Draft provider returned a risk outside the deterministic policy")
    recommendation = str(candidate.get("recommendation") or "").strip()
    if not recommendation:
        raise ValueError("Draft provider returned an empty recommendation")
    return {
        "report_id": "CR-2026-Q3-SUP-1042",
        "supplier_id": source_case["supplier"]["supplier_id"],
        "period": source_case["reporting_period"],
        "risk": expected_risk,
        "findings": expected_findings,
        "recommendation": recommendation,
        "rule_ids": list(context["semantic"].get("rule_ids", [])),
        "skill_versions": {
            str(item.get("name")): str(item.get("sha"))
            for item in (loaded_skills or [])
        },
        "freshness_policy_days": (freshness_result or {}).get("policy_limit_days"),
        "sanctions_status": (sanctions_result or {}).get("status"),
        "risk_score": (risk_assessment or {}).get("score"),
        "remediation_plan": json_safe(remediation_plan or {}),
    }


class DeterministicComplianceDrafter:
    """Reproducible provider used to isolate durability from model variance."""

    def plan(
        self,
        *,
        objective: str,
        skill_manifest: str,
        skill_candidates: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        available = {str(item["name"]) for item in skill_candidates}
        preferred = [
            "high-risk-supplier-review",
            "evidence-freshness-review",
            "sanctions-screening",
            "supplier-risk-scoring",
            "remediation-and-publication",
        ]
        selected = [name for name in preferred if name in available]
        if "high-risk-supplier-review" not in selected:
            raise RuntimeError("The canonical high-risk supplier skill was not retrieved")
        return {
            "selected_skills": selected,
            "tool_query": (
                "load supplier case validate evidence freshness screen sanctions "
                "calculate risk build remediation verify published report"
            ),
            "rationale": "Use the canonical procedure plus its focused supporting skills.",
            "objective": objective,
            "manifest_seen": skill_manifest,
        }

    def draft(
        self,
        *,
        source_case: Mapping[str, Any],
        context: Mapping[str, Any],
        freshness_result: Mapping[str, Any] | None = None,
        sanctions_result: Mapping[str, Any] | None = None,
        risk_assessment: Mapping[str, Any] | None = None,
        remediation_plan: Mapping[str, Any] | None = None,
        loaded_skills: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        findings = _authoritative_findings(source_case)
        risk = (
            "blocked_pending_remediation"
            if any(item["severity"] == "blocking" for item in findings)
            else "review"
        )
        return _ground_report(
            {
                "risk": risk,
                "findings": findings,
                "recommendation": (
                    "Accept only with a named remediation owner and a replacement "
                    "restricted-substance certificate; human approval is mandatory."
                ),
            },
            source_case=source_case,
            context=context,
            freshness_result=freshness_result,
            sanctions_result=sanctions_result,
            risk_assessment=risk_assessment,
            remediation_plan=remediation_plan,
            loaded_skills=loaded_skills,
        )

    @staticmethod
    def distill_skill(*, recipe: Mapping[str, Any]) -> dict[str, str]:
        return {
            "description": (
                "Execute the recurring, verified supplier-compliance path with semantic "
                "skill and tool retrieval, sandboxed tools, human approval, and host verification."
            ),
            "body": (
                "1. Retrieve the smallest relevant skill manifest and load the selected full skills.\n"
                "2. Retrieve only the required tool contracts by meaning.\n"
                "3. Run case intake, freshness, sanctions, risk, remediation, and verification tools in fresh sandboxes.\n"
                "4. Draft from verified outputs, then pause on the exact digest for a named owner.\n"
                "5. Publish once, verify independently, and retain the recipe outcome counters."
            ),
        }

    @staticmethod
    def status() -> dict[str, Any]:
        return {
            "provider": "deterministic compliance policy",
            "model_provider": "none",
            "model": "none",
            "model_backed": False,
            "llm_driven": False,
            "profile": "deterministic offline/test driver",
        }


class OpenAIResponsesComplianceDrafter:
    """Optional model-backed drafter with strict structured-output grounding."""

    response_schema = {
        "type": "object",
        "properties": {
            "risk": {
                "type": "string",
                "enum": ["blocked_pending_remediation", "review"],
            },
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "control_id": {"type": "string"},
                        "evidence_id": {"type": "string"},
                        "status": {"type": "string"},
                        "severity": {
                            "type": "string",
                            "enum": ["clear", "material", "blocking"],
                        },
                    },
                    "required": [
                        "control_id",
                        "evidence_id",
                        "status",
                        "severity",
                    ],
                    "additionalProperties": False,
                },
            },
            "recommendation": {"type": "string", "minLength": 1},
        },
        "required": ["risk", "findings", "recommendation"],
        "additionalProperties": False,
    }

    plan_schema = {
        "type": "object",
        "properties": {
            "selected_skills": {"type": "array", "items": {"type": "string"}},
            "tool_query": {"type": "string", "minLength": 1},
            "rationale": {"type": "string", "minLength": 1},
        },
        "required": ["selected_skills", "tool_query", "rationale"],
        "additionalProperties": False,
    }

    distillation_schema = {
        "type": "object",
        "properties": {
            "description": {"type": "string", "minLength": 1},
            "body": {"type": "string", "minLength": 1},
        },
        "required": ["description", "body"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        course_settings: AdvancedSettings = default_settings,
        *,
        client: Any = None,
    ) -> None:
        if not course_settings.openai_api_key and client is None:
            raise RuntimeError(
                "ADVANCED_USE_MODEL_SYNTHESIS=true requires a valid OPENAI_API_KEY"
            )
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=course_settings.openai_api_key)
        self.client = client
        self.model = course_settings.openai_model

    def plan(
        self,
        *,
        objective: str,
        skill_manifest: str,
        skill_candidates: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        response = self.client.responses.create(
            model=self.model,
            store=False,
            instructions=(
                "Plan a high-risk supplier review. Select only skill names in the "
                "manifest. The canonical high-risk-supplier-review skill is mandatory. "
                "Return a semantic tool-search query, not tool calls."
            ),
            input=json.dumps(
                {"objective": objective, "skill_manifest": skill_manifest},
                sort_keys=True,
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "supplier_review_plan",
                    "schema": self.plan_schema,
                    "strict": True,
                }
            },
            max_output_tokens=1200,
        )
        plan = json.loads(response.output_text)
        available = {str(item["name"]) for item in skill_candidates}
        selected = [str(item) for item in plan["selected_skills"]]
        if not selected or not set(selected) <= available:
            raise ValueError("Planner selected a skill outside the retrieved manifest")
        if "high-risk-supplier-review" not in selected:
            raise ValueError("Planner omitted the mandatory canonical review skill")
        return {**plan, "objective": objective, "manifest_seen": skill_manifest}

    def draft(
        self,
        *,
        source_case: Mapping[str, Any],
        context: Mapping[str, Any],
        freshness_result: Mapping[str, Any] | None = None,
        sanctions_result: Mapping[str, Any] | None = None,
        risk_assessment: Mapping[str, Any] | None = None,
        remediation_plan: Mapping[str, Any] | None = None,
        loaded_skills: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        response = self.client.responses.create(
            model=self.model,
            store=False,
            instructions=(
                "Draft a supplier-compliance report from only the supplied JSON. "
                "Preserve every control_id, evidence_id, and status exactly. Apply "
                "the supplied SOP and rules. Do not claim approval or publication."
            ),
            input=json.dumps(
                {
                    "source_case": json_safe(source_case),
                    "procedural_memory": json_safe(context["procedural"]),
                    "semantic_memory": json_safe(context["semantic"]),
                    "selected_skills": [
                        {
                            "name": item.get("name"),
                            "sha": item.get("sha"),
                            "skill_md": item.get("skill_md"),
                        }
                        for item in (loaded_skills or [])
                    ],
                    "sandbox_verified_outputs": {
                        "freshness": json_safe(freshness_result or {}),
                        "sanctions": json_safe(sanctions_result or {}),
                        "risk": json_safe(risk_assessment or {}),
                        "remediation": json_safe(remediation_plan or {}),
                    },
                },
                sort_keys=True,
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "supplier_compliance_report",
                    "schema": self.response_schema,
                    "strict": True,
                }
            },
            max_output_tokens=2400,
        )
        candidate = json.loads(response.output_text)
        return _ground_report(
            candidate,
            source_case=source_case,
            context=context,
            freshness_result=freshness_result,
            sanctions_result=sanctions_result,
            risk_assessment=risk_assessment,
            remediation_plan=remediation_plan,
            loaded_skills=loaded_skills,
        )

    def distill_skill(self, *, recipe: Mapping[str, Any]) -> dict[str, str]:
        response = self.client.responses.create(
            model=self.model,
            store=False,
            instructions=(
                "Distil the verified workflow recipe into a short parameterised "
                "procedure. Preserve approval, sandbox, and host-verification boundaries. "
                "Do not include supplier-specific identifiers."
            ),
            input=json.dumps(json_safe(recipe), sort_keys=True),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "workflow_skill_distillation",
                    "schema": self.distillation_schema,
                    "strict": True,
                }
            },
            max_output_tokens=1600,
        )
        return json.loads(response.output_text)

    def status(self) -> dict[str, Any]:
        return {
            "provider": "OpenAI Responses API",
            "model_provider": "OpenAI",
            "model": self.model,
            "model_backed": True,
            "llm_driven": True,
            "structured_output": "strict JSON Schema",
            "grounding_verifier": "deterministic identifier/status/severity check",
        }


def create_report_drafter(
    course_settings: AdvancedSettings = default_settings,
) -> DeterministicComplianceDrafter | OpenAIResponsesComplianceDrafter:
    if course_settings.use_model_synthesis:
        return OpenAIResponsesComplianceDrafter(course_settings)
    return DeterministicComplianceDrafter()


__all__ = [
    "DeterministicComplianceDrafter",
    "OpenAIResponsesComplianceDrafter",
    "create_report_drafter",
]
