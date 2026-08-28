"""Supplier-review tools and their governed sandbox execution boundary."""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from memorizz.sandbox import E2BSandboxProvider, ExecutionResult, SandboxProvider

from .catalog import HarnessCatalog
from .config import AdvancedSettings, settings as default_settings
from .fixtures import compliance_case
from .persistence import json_safe, stable_hash


TOOL_INPUT_PATH = "/home/user/tool-input.json"
TOOL_PROGRAM_PATH = "/home/user/tool-runner.py"
TOOL_OUTPUT_PATH = "/home/user/tool-output.json"
CASE_JSON = json.dumps(compliance_case(), sort_keys=True)


def load_supplier_case(case_id: str) -> dict[str, Any]:
    """Return the authoritative synthetic case selected by its stable identifier."""

    case = json.loads(CASE_JSON)
    expected = f"{case['supplier']['supplier_id']}:{case['reporting_period']}"
    if case_id != expected:
        return {"error": "unknown case_id", "case_id": case_id}
    return case


def validate_evidence_freshness(
    controls: Sequence[Mapping[str, Any]], maximum_age_days: int = 365
) -> dict[str, Any]:
    """Normalize evidence status without changing authoritative identifiers."""

    findings = []
    for control in controls:
        age = int(control["evidence_age_days"])
        original_status = str(control["status"])
        expired = age > int(maximum_age_days) or original_status == "expired"
        severity = "blocking" if expired else "material" if original_status == "open" else "clear"
        findings.append(
            {
                "control_id": str(control["control_id"]),
                "evidence_id": str(control["evidence_id"]),
                "original_status": original_status,
                "evidence_age_days": age,
                "freshness_status": "expired" if expired else "current",
                "severity": severity,
            }
        )
    return {
        "policy_limit_days": int(maximum_age_days),
        "findings": findings,
        "blocking_control_ids": [
            item["control_id"] for item in findings if item["severity"] == "blocking"
        ],
    }


def screen_supplier_sanctions(
    supplier: Mapping[str, Any], screening_record: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate only the supplied authoritative screening record."""

    missing = not screening_record.get("screening_id")
    possible_match = bool(screening_record.get("possible_match"))
    return {
        "supplier_id": str(supplier["supplier_id"]),
        "screening_id": str(screening_record.get("screening_id") or "missing"),
        "checked_at": str(screening_record.get("checked_at") or "unknown"),
        "status": "blocked" if missing or possible_match else "clear",
        "possible_match": possible_match,
        "reason": (
            "screening_record_missing"
            if missing
            else "possible_sanctions_match"
            if possible_match
            else "authoritative_record_clear"
        ),
    }


def calculate_supplier_risk(
    supplier: Mapping[str, Any],
    freshness_result: Mapping[str, Any],
    sanctions_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Compute a deterministic score while retaining hard policy blocks."""

    findings = list(freshness_result["findings"])
    blocking = [item["control_id"] for item in findings if item["severity"] == "blocking"]
    material = [item["control_id"] for item in findings if item["severity"] == "material"]
    components = {
        "high_risk_supplier": 25 if supplier.get("risk_tier") == "high" else 0,
        "blocking_evidence": 45 * len(blocking),
        "material_findings": 15 * len(material),
        "sanctions_block": 100 if sanctions_result.get("status") == "blocked" else 0,
    }
    score = min(100, sum(components.values()))
    hard_block = bool(blocking) or sanctions_result.get("status") == "blocked"
    return {
        "score": score,
        "band": "critical" if score >= 80 else "high" if score >= 50 else "medium" if score >= 25 else "low",
        "route": "blocked_pending_remediation" if hard_block else "owner_review",
        "blocking_control_ids": blocking,
        "material_control_ids": material,
        "components": components,
    }


def build_remediation_plan(
    supplier_id: str, findings: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Create deterministic, owned actions for non-clear findings."""

    actions = []
    for finding in findings:
        if finding["severity"] == "clear":
            continue
        blocking = finding["severity"] == "blocking"
        actions.append(
            {
                "action_id": f"ACT-{finding['control_id']}",
                "supplier_id": supplier_id,
                "control_id": finding["control_id"],
                "evidence_id": finding["evidence_id"],
                "owner_role": "compliance-owner" if blocking else "supplier-quality-manager",
                "due_in_days": 7 if blocking else 30,
                "closure_evidence": (
                    "replacement certificate" if blocking else "verified remediation update"
                ),
            }
        )
    return {
        "supplier_id": supplier_id,
        "actions": actions,
        "blocking_actions": sum(action["due_in_days"] == 7 for action in actions),
    }


def _package_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def verify_report_package(publication: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the immutable report digest and the bound human decision."""

    report = publication.get("report") or {}
    approval = publication.get("approval") or {}
    checks = {
        "report_digest_matches": publication.get("immutable_digest") == _package_digest(report),
        "named_human_approved": bool(approval.get("approved") and approval.get("decided_by")),
        "report_id_bound": bool(
            report.get("report_id") and approval.get("report_id") == report.get("report_id")
        ),
        "publication_id_bound": publication.get("publication_id")
        == f"PUB-{report.get('report_id')}",
    }
    return {"verified": all(checks.values()), "checks": checks}


# Extra registered tools make semantic top-k retrieval meaningful.  They remain
# pure and sandboxable, but the selected supplier-review skills do not authorize
# them for this workflow.
def convert_currency(amount: float, rate: float) -> dict[str, Any]:
    return {"converted_amount": round(float(amount) * float(rate), 2)}


def schedule_supplier_visit(supplier_id: str, requested_date: str) -> dict[str, Any]:
    return {"supplier_id": supplier_id, "requested_date": requested_date, "status": "proposal_only"}


def translate_evidence_summary(text: str, language: str) -> dict[str, Any]:
    return {"text": text, "language": language, "status": "translation_not_configured"}


def archive_closed_case(case_id: str) -> dict[str, Any]:
    return {"case_id": case_id, "status": "archive_proposal_only"}


def _sandbox_program(fn: Callable[..., Any], *, prelude: str = "") -> str:
    helpers = ""
    if fn is verify_report_package:
        helpers = textwrap.dedent(inspect.getsource(_package_digest))
    return (
        "from __future__ import annotations\n"
        "import json\n"
        "from hashlib import sha256\n"
        "from pathlib import Path\n"
        "from typing import Any, Mapping, Sequence\n\n"
        "BASE = Path(globals().get('__file__', '/home/user/tool-runner.py')).parent\n"
        "INPUT = BASE / 'tool-input.json'\n"
        "OUTPUT = BASE / 'tool-output.json'\n"
        f"{prelude}\n{helpers}\n{textwrap.dedent(inspect.getsource(fn))}\n"
        "payload = json.loads(INPUT.read_text(encoding='utf-8'))\n"
        f"result = {fn.__name__}(**payload['arguments'])\n"
        "OUTPUT.write_text(json.dumps(result, sort_keys=True), encoding='utf-8')\n"
        "print(json.dumps(result, sort_keys=True))\n"
    )


class LocalProcessSandboxProvider(SandboxProvider):
    """Labelled local-process fallback for tests; it does not claim remote isolation."""

    provider_name = "local-process-sandbox-test-profile"

    def __init__(self) -> None:
        super().__init__()
        self._temporary = tempfile.TemporaryDirectory(prefix="workflow-tool-sandbox-")
        self.root = Path(self._temporary.name)
        self.closed = False

    def _path(self, remote_path: str) -> Path:
        return self.root / Path(remote_path).name

    def get_config(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "test_profile": True,
            "isolation_proven": False,
            "allow_internet_access": None,
            "egress_policy_enforcement": "not-proven-in-local-test-profile",
        }

    def write_file(self, path: str, content: str) -> bool:
        self._path(path).write_text(str(content), encoding="utf-8")
        return True

    def read_file(self, path: str) -> str | None:
        target = self._path(path)
        return target.read_text(encoding="utf-8") if target.exists() else None

    def execute_code(
        self,
        code: str,
        language: str = "python",
        timeout: int = 30,
        envs: dict[str, str] | None = None,
    ) -> ExecutionResult:
        del code
        if language != "python":
            return ExecutionResult(error="python only", exit_code=2)
        try:
            completed = subprocess.run(
                [sys.executable, "-I", str(self._path(TOOL_PROGRAM_PATH))],
                cwd=self.root,
                env=dict(envs or {}),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return ExecutionResult(
                stdout=completed.stdout.splitlines(),
                stderr=completed.stderr.splitlines(),
                exit_code=completed.returncode,
                metadata={**self.get_config(), "environment_variable_count": len(envs or {})},
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(error="execution timed out", exit_code=124)

    def close(self) -> None:
        if not self.closed:
            self._temporary.cleanup()
            self.closed = True


def _validate_arguments(schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> None:
    required = set(schema.get("required") or [])
    properties = dict(schema.get("properties") or {})
    missing = sorted(required - set(arguments))
    if missing:
        raise ValueError("tool arguments missing: " + ", ".join(missing))
    if schema.get("additionalProperties") is False:
        extra = sorted(set(arguments) - set(properties))
        if extra:
            raise ValueError("unexpected tool arguments: " + ", ".join(extra))
    python_types = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": (list, tuple),
        "object": Mapping,
    }
    for name, value in arguments.items():
        expected_name = (properties.get(name) or {}).get("type")
        expected = python_types.get(expected_name)
        if expected is not None and not isinstance(value, expected):
            raise TypeError(f"tool argument {name!r} must be {expected_name}")


class SandboxedToolExecutor:
    """Resolve a registered callable, run its program in a sandbox, and verify output."""

    def __init__(
        self,
        catalog: HarnessCatalog,
        course_settings: AdvancedSettings = default_settings,
        *,
        provider_factory: Callable[[], SandboxProvider] | None = None,
    ) -> None:
        self.catalog = catalog
        self.settings = course_settings
        self.provider_factory = provider_factory
        self.invocations = 0
        self.sessions_closed = 0
        self._lock = threading.RLock()

    def _provider(self) -> SandboxProvider:
        if self.provider_factory is not None:
            return self.provider_factory()
        if self.settings.e2b_api_key:
            return E2BSandboxProvider(
                api_key=self.settings.e2b_api_key,
                session_timeout=self.settings.e2b_session_timeout,
                max_execution_timeout=self.settings.e2b_execution_timeout,
                allow_internet_access=False,
            )
        return LocalProcessSandboxProvider()

    def execute(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        registered = self.catalog.resolve_tool(name)
        schema = registered["schema"]["parameters"]
        safe_arguments = json_safe(dict(arguments))
        _validate_arguments(schema, safe_arguments)
        expected = json_safe(registered["fn"](**safe_arguments))
        payload = {"tool": name, "arguments": safe_arguments}
        provider: SandboxProvider | None = None
        envelope: dict[str, Any] | None = None
        with self._lock:
            self.invocations += 1
        try:
            provider = self._provider()
            config = dict(provider.get_config())
            test_profile = bool(config.get("test_profile"))
            if not test_profile and config.get("allow_internet_access") is not False:
                raise RuntimeError("remote sandbox egress policy is not fail-closed")
            if not provider.write_file(TOOL_INPUT_PATH, json.dumps(payload, sort_keys=True)):
                raise RuntimeError("sandbox input upload failed")
            if not provider.write_file(TOOL_PROGRAM_PATH, registered["sandbox_program"]):
                raise RuntimeError("sandbox program upload failed")
            execution = provider.execute_code(
                f"exec(open({TOOL_PROGRAM_PATH!r}, encoding='utf-8').read())",
                language="python",
                timeout=self.settings.e2b_execution_timeout,
                envs={},
            )
            if not execution.success:
                detail = execution.error or (execution.stderr[-1] if execution.stderr else "unknown error")
                raise RuntimeError(f"sandbox execution failed: {detail}")
            rendered = provider.read_file(TOOL_OUTPUT_PATH)
            if not rendered and execution.stdout:
                rendered = execution.stdout[-1]
            observed = json.loads(str(rendered or ""))
            if observed != expected:
                raise RuntimeError("sandbox output did not match host recomputation")
            envelope = {
                "tool": name,
                "input": {
                    "arguments": safe_arguments,
                    "digest": stable_hash(payload),
                },
                "execution": {
                    "provider": config.get("provider", type(provider).__name__),
                    "test_profile": test_profile,
                    "isolation_proven": bool(config.get("isolation_proven", not test_profile)),
                    "egress_allowed": False if not test_profile else "not proven",
                    "egress_policy_enforcement": config.get("egress_policy_enforcement"),
                    "environment_variable_count": 0,
                    "timeout_seconds": self.settings.e2b_execution_timeout,
                    "program_digest": stable_hash(registered["sandbox_program"]),
                    "exit_code": execution.exit_code,
                    "session_closed": False,
                },
                "output": {
                    "result": observed,
                    "digest": stable_hash(observed),
                    "host_recomputation_matched": True,
                },
            }
        finally:
            if provider is not None:
                provider.close()
                with self._lock:
                    self.sessions_closed += 1
                if envelope is not None:
                    envelope["execution"]["session_closed"] = True
        if envelope is None:
            raise RuntimeError("sandbox tool execution produced no envelope")
        return envelope

    def status(self) -> dict[str, Any]:
        live = self.provider_factory is None and bool(self.settings.e2b_api_key)
        return {
            "provider": "MemoRizz E2BSandboxProvider / E2B" if live else "local subprocess test profile",
            "live_remote_isolation": live,
            "egress": "blocked" if live else "not proven in local test profile",
            "forwarded_environment_variables": 0,
            "execution_timeout_seconds": self.settings.e2b_execution_timeout,
            "invocations": self.invocations,
            "sessions_closed": self.sessions_closed,
        }


def _object_schema(properties: Mapping[str, Any], required: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": json_safe(dict(properties)),
        "required": list(required),
        "additionalProperties": False,
    }


def register_workflow_tools(catalog: HarnessCatalog) -> list[str]:
    """Persist model-facing contracts and retain executable halves in Python."""

    definitions = [
        (
            "load_supplier_case",
            load_supplier_case,
            "Load the authoritative supplier case, control evidence, and screening record by case ID.",
            _object_schema({"case_id": {"type": "string"}}, ["case_id"]),
            "case intake",
            ["fetch case", "open supplier review", "load evidence bundle"],
            ["load SUP-1042:2026-Q3"],
            "At the start of a supplier review.",
            "When a case is already present in checkpointed state.",
            f"CASE_JSON = {CASE_JSON!r}\n",
        ),
        (
            "validate_evidence_freshness",
            validate_evidence_freshness,
            "Check control evidence ages, preserve IDs, and mark evidence older than policy as blocking.",
            _object_schema(
                {
                    "controls": {"type": "array"},
                    "maximum_age_days": {"type": "integer"},
                },
                ["controls", "maximum_age_days"],
            ),
            "compliance",
            ["certificate expiry", "document age", "freshness check"],
            ["check certificates against 365 days"],
            "After the evidence bundle is loaded.",
            "For sanctions or publication approval.",
            "",
        ),
        (
            "screen_supplier_sanctions",
            screen_supplier_sanctions,
            "Evaluate an authoritative sanctions-screening record and fail closed on a possible match.",
            _object_schema(
                {
                    "supplier": {"type": "object"},
                    "screening_record": {"type": "object"},
                },
                ["supplier", "screening_record"],
            ),
            "compliance",
            ["watchlist", "restricted party", "sanctions check"],
            ["screen supplier using supplied record"],
            "For every supplier review.",
            "For open-web identity research.",
            "",
        ),
        (
            "calculate_supplier_risk",
            calculate_supplier_risk,
            "Combine supplier tier, evidence findings, and sanctions status into an explainable risk route.",
            _object_schema(
                {
                    "supplier": {"type": "object"},
                    "freshness_result": {"type": "object"},
                    "sanctions_result": {"type": "object"},
                },
                ["supplier", "freshness_result", "sanctions_result"],
            ),
            "risk",
            ["risk score", "triage", "risk band"],
            ["score a high-risk supplier after evidence checks"],
            "After freshness and sanctions checks.",
            "Before source results have been verified.",
            "",
        ),
        (
            "build_remediation_plan",
            build_remediation_plan,
            "Create owned, time-bounded remediation actions for blocking and material findings.",
            _object_schema(
                {"supplier_id": {"type": "string"}, "findings": {"type": "array"}},
                ["supplier_id", "findings"],
            ),
            "remediation",
            ["corrective action", "closure plan", "assign owner"],
            ["create a replacement-certificate action"],
            "When findings are blocking or material.",
            "To approve or publish a report.",
            "",
        ),
        (
            "verify_report_package",
            verify_report_package,
            "Verify the report digest, human decision binding, report ID, and publication ID.",
            _object_schema({"publication": {"type": "object"}}, ["publication"]),
            "verification",
            ["validate artifact", "check digest", "publication attestation"],
            ["verify the published report package"],
            "After the idempotent publication operation.",
            "Before a human decision exists.",
            "",
        ),
        (
            "convert_currency",
            convert_currency,
            "Convert a monetary amount using an already supplied exchange rate.",
            _object_schema(
                {"amount": {"type": "number"}, "rate": {"type": "number"}},
                ["amount", "rate"],
            ),
            "finance",
            ["fx", "currency conversion"],
            ["convert 100 USD at rate 0.8"],
            "For explicit currency calculations.",
            "For compliance risk decisions.",
            "",
        ),
        (
            "schedule_supplier_visit",
            schedule_supplier_visit,
            "Prepare a non-binding supplier-visit scheduling proposal.",
            _object_schema(
                {"supplier_id": {"type": "string"}, "requested_date": {"type": "string"}},
                ["supplier_id", "requested_date"],
            ),
            "operations",
            ["site visit", "calendar proposal"],
            ["propose a factory visit"],
            "When an operator asks for a visit proposal.",
            "To close evidence findings automatically.",
            "",
        ),
        (
            "translate_evidence_summary",
            translate_evidence_summary,
            "Prepare a translation request for an evidence summary.",
            _object_schema(
                {"text": {"type": "string"}, "language": {"type": "string"}},
                ["text", "language"],
            ),
            "language",
            ["translation", "localize evidence"],
            ["translate summary to Portuguese"],
            "For operator-facing localization.",
            "For changing authoritative evidence.",
            "",
        ),
        (
            "archive_closed_case",
            archive_closed_case,
            "Prepare an archive proposal for a closed supplier case.",
            _object_schema({"case_id": {"type": "string"}}, ["case_id"]),
            "records",
            ["close case", "retention", "archive"],
            ["archive a completed review"],
            "Only after a case is closed under retention policy.",
            "During an active review.",
            "",
        ),
    ]
    registered = []
    for (
        name,
        fn,
        description,
        schema,
        category,
        synonyms,
        examples,
        when_to_use,
        when_not,
        prelude,
    ) in definitions:
        catalog.register_tool(
            name,
            fn,
            description,
            schema,
            sandbox_program=_sandbox_program(fn, prelude=prelude),
            category=category,
            synonyms=synonyms,
            examples=examples,
            when_to_use=when_to_use,
            when_not=when_not,
        )
        registered.append(name)
    return registered


__all__ = [
    "LocalProcessSandboxProvider",
    "SandboxedToolExecutor",
    "register_workflow_tools",
]
