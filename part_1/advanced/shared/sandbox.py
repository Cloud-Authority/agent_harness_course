"""Governed E2B execution used by the advanced MetaHarness course.

The live implementation delegates isolation to MemoRizz's published
``E2BSandboxProvider``.  A deterministic test double is supplied only for the
labelled, no-network notebook and acceptance-test profile; its metadata makes
clear that it is not evidence of remote isolation.
"""

from __future__ import annotations

import hashlib
import json
import threading
from importlib.metadata import version
from pathlib import Path
from typing import Any, Callable

from memorizz.metaharness import (
    AdapterOutcome,
    AgentHarness,
    HarnessCapabilities,
    HarnessContextPack,
    HarnessEvent,
    HarnessEventType,
    HarnessTask,
)
from memorizz.sandbox import E2BSandboxProvider, ExecutionResult, SandboxProvider


SANDBOX_POLICY_VERSION = "AUTHZ-RISK-2026-08"
SANDBOX_INPUT_PATH = "/home/user/authorization-input.json"
SANDBOX_PROGRAM_PATH = "/home/user/policy_runner.py"
SANDBOX_RESULT_PATH = "/home/user/authorization-result.json"


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def authorization_fixture() -> dict[str, Any]:
    """Return a synthetic financial-services authorization review fixture."""

    return {
        "policy_version": SANDBOX_POLICY_VERSION,
        "approval_limit_usd": 50_000,
        "requests": [
            {
                "request_id": "payment-1042",
                "role": "payments-analyst",
                "amount_usd": 12_500,
                "mfa": True,
                "sanctions_match": False,
            },
            {
                "request_id": "payment-1043",
                "role": "payments-admin",
                "amount_usd": 81_000,
                "mfa": True,
                "sanctions_match": False,
            },
            {
                "request_id": "payment-1044",
                "role": "payments-admin",
                "amount_usd": 900,
                "mfa": False,
                "sanctions_match": False,
            },
            {
                "request_id": "payment-1045",
                "role": "payments-analyst",
                "amount_usd": 250,
                "mfa": True,
                "sanctions_match": True,
            },
        ],
    }


def evaluate_authorization_policy(payload: dict[str, Any]) -> dict[str, Any]:
    """Host reference implementation used to verify the sandbox result."""

    limit = int(payload["approval_limit_usd"])
    decisions: list[dict[str, Any]] = []
    for request in payload["requests"]:
        reasons: list[str] = []
        if bool(request.get("sanctions_match")):
            reasons.append("sanctions_match")
        if str(request.get("role", "")).endswith("admin") and not bool(
            request.get("mfa")
        ):
            reasons.append("admin_without_mfa")
        if int(request.get("amount_usd", 0)) > limit:
            reasons.append("amount_requires_human_approval")
        if "sanctions_match" in reasons or "admin_without_mfa" in reasons:
            decision = "deny"
        elif reasons:
            decision = "review"
        else:
            decision = "allow"
        decisions.append(
            {
                "request_id": request["request_id"],
                "decision": decision,
                "reasons": reasons,
            }
        )
    result: dict[str, Any] = {
        "schema_version": "advanced.e2b.authorization.v1",
        "policy_version": payload["policy_version"],
        "input_digest": _digest(payload),
        "decisions": decisions,
        "summary": {
            "allow": sum(item["decision"] == "allow" for item in decisions),
            "review": sum(item["decision"] == "review" for item in decisions),
            "deny": sum(item["decision"] == "deny" for item in decisions),
        },
    }
    result["decision_digest"] = _digest(result)
    return result


# This program is intentionally dependency-free and receives no credentials.  It is
# written into the remote sandbox, run there, and independently recomputed by the host.
POLICY_PROGRAM = f'''\
import hashlib
import json
from pathlib import Path

INPUT = Path({SANDBOX_INPUT_PATH!r})
OUTPUT = Path({SANDBOX_RESULT_PATH!r})

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()

payload = json.loads(INPUT.read_text(encoding="utf-8"))
limit = int(payload["approval_limit_usd"])
decisions = []
for request in payload["requests"]:
    reasons = []
    if bool(request.get("sanctions_match")):
        reasons.append("sanctions_match")
    if str(request.get("role", "")).endswith("admin") and not bool(request.get("mfa")):
        reasons.append("admin_without_mfa")
    if int(request.get("amount_usd", 0)) > limit:
        reasons.append("amount_requires_human_approval")
    if "sanctions_match" in reasons or "admin_without_mfa" in reasons:
        decision = "deny"
    elif reasons:
        decision = "review"
    else:
        decision = "allow"
    decisions.append({{
        "request_id": request["request_id"],
        "decision": decision,
        "reasons": reasons,
    }})

result = {{
    "schema_version": "advanced.e2b.authorization.v1",
    "policy_version": payload["policy_version"],
    "input_digest": digest(payload),
    "decisions": decisions,
    "summary": {{
        "allow": sum(item["decision"] == "allow" for item in decisions),
        "review": sum(item["decision"] == "review" for item in decisions),
        "deny": sum(item["decision"] == "deny" for item in decisions),
    }},
}}
result["decision_digest"] = digest(result)
OUTPUT.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
print(json.dumps(result, sort_keys=True))
'''


class DeterministicE2BTestDouble(SandboxProvider):
    """No-network test double for course mechanics; never presented as isolation."""

    provider_name = "e2b-test-double"

    def __init__(self) -> None:
        super().__init__()
        self.files: dict[str, str] = {}
        self.closed = False
        self.execute_calls = 0

    def get_config(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "isolation_proven": False,
            "egress_allowed": False,
            "profile": "deterministic-no-network-test-double",
        }

    def execute_code(
        self,
        code: str,
        language: str = "python",
        timeout: int = 30,
        envs: dict[str, str] | None = None,
    ) -> ExecutionResult:
        self.execute_calls += 1
        payload = json.loads(self.files[SANDBOX_INPUT_PATH])
        result = evaluate_authorization_policy(payload)
        rendered = json.dumps(result, sort_keys=True)
        self.files[SANDBOX_RESULT_PATH] = rendered
        return ExecutionResult(
            stdout=[rendered],
            exit_code=0,
            metadata={
                **self.get_config(),
                "execution_timeout": timeout,
                "environment_variable_count": len(envs or {}),
            },
        )

    def write_file(self, path: str, content: str) -> bool:
        self.files[str(path)] = str(content)
        return True

    def read_file(self, path: str) -> str | None:
        return self.files.get(str(path))

    def close(self) -> None:
        self.closed = True


class E2BAuthorizationHarness(AgentHarness):
    """MemoRizz AgentHarness adapter for an egress-blocked E2B policy run."""

    name = "e2b-authorization"

    def __init__(
        self,
        api_key: str = "",
        *,
        provider_factory: Callable[[], SandboxProvider] | None = None,
        session_timeout: int = 120,
        execution_timeout: int = 30,
    ) -> None:
        self.api_key = str(api_key or "")
        self.provider_factory = provider_factory
        self.session_timeout = max(30, min(int(session_timeout), 600))
        self.execution_timeout = max(1, min(int(execution_timeout), 120))
        self.invocations = 0
        self.sessions_closed = 0
        self._lock = threading.RLock()

    @property
    def test_double(self) -> bool:
        return self.provider_factory is not None

    def probe(self) -> HarnessCapabilities:
        available = bool(self.api_key) or self.test_double
        return HarnessCapabilities(
            name=self.name,
            available=available,
            version=(
                "deterministic-test-double"
                if self.test_double
                else f"memorizz {version('memorizz')} / e2b {version('e2b')}"
            ),
            command="MemoRizz E2BSandboxProvider",
            structured_events=True,
            usage_reporting=True,
            requires_external_isolation=False,
            error_code=None if available else "authentication_required",
            error=None if available else "An E2B API key was not supplied.",
            remediation=(
                None
                if available
                else "Enter E2B_API_KEY with getpass in the notebook or set it in the appbook server process."
            ),
            metadata={
                "network_modes": ["full"],
                "task_tool_policy": True,
                "isolation_provider": "E2B",
                "sandbox_egress": "blocked",
                "test_double": self.test_double,
            },
        )

    def _provider(self) -> SandboxProvider:
        if self.provider_factory is not None:
            return self.provider_factory()
        return E2BSandboxProvider(
            api_key=self.api_key,
            session_timeout=self.session_timeout,
            max_execution_timeout=self.execution_timeout,
            allow_internet_access=False,
        )

    def run(
        self,
        task: HarnessTask,
        *,
        workspace: Path,
        context_pack: HarnessContextPack,
        emit: Callable[[HarnessEvent], None],
        cancel_event: threading.Event,
    ) -> AdapterOutcome:
        if cancel_event.is_set():
            return AdapterOutcome(
                error_code="canceled",
                error="Canceled before the sandbox session was created.",
                exit_code=1,
            )
        payload = task.context.get("authorization_fixture")
        if not isinstance(payload, dict):
            return AdapterOutcome(
                error_code="invalid_sandbox_input",
                error="The authorization fixture is missing or invalid.",
                exit_code=1,
            )
        expected = evaluate_authorization_policy(payload)
        provider: SandboxProvider | None = None
        terminated = False
        with self._lock:
            self.invocations += 1
        emit(
            HarnessEvent(
                task.run_id,
                HarnessEventType.STATUS,
                {
                    "phase": "sandbox_create",
                    "provider": "e2b",
                    "sandbox_egress": "blocked",
                },
            )
        )
        try:
            provider = self._provider()
            config = provider.get_config()
            if config.get("allow_internet_access") is True or config.get(
                "egress_allowed"
            ) is True:
                raise RuntimeError("sandbox egress policy is not fail-closed")
            if not provider.write_file(SANDBOX_INPUT_PATH, _canonical(payload)):
                raise RuntimeError("sandbox input upload failed")
            if not provider.write_file(SANDBOX_PROGRAM_PATH, POLICY_PROGRAM):
                raise RuntimeError("sandbox program upload failed")
            emit(
                HarnessEvent(
                    task.run_id,
                    HarnessEventType.TOOL_CALL,
                    {
                        "id": "e2b-policy-execution",
                        "name": "execute_code",
                        "language": "python",
                        "timeout_seconds": self.execution_timeout,
                        "environment_variable_count": 0,
                    },
                )
            )
            execution = provider.execute_code(
                f"exec(open({SANDBOX_PROGRAM_PATH!r}, encoding='utf-8').read())",
                language="python",
                timeout=self.execution_timeout,
                envs={},
            )
            if not execution.success:
                raise RuntimeError("sandbox execution did not complete successfully")
            rendered = provider.read_file(SANDBOX_RESULT_PATH)
            if not rendered and execution.stdout:
                rendered = execution.stdout[-1]
            observed = json.loads(str(rendered or ""))
            if observed != expected:
                raise RuntimeError("host recomputation did not match sandbox output")
            attestation = {
                "schema_version": "advanced.e2b.attestation.v1",
                "provider": execution.metadata.get("provider", "e2b"),
                "test_double": self.test_double,
                "isolation_proven": not self.test_double,
                "sandbox_egress_allowed": False,
                "environment_variable_count": 0,
                "input_digest": observed["input_digest"],
                "decision_digest": observed["decision_digest"],
                "summary": observed["summary"],
                "host_recomputation_matched": True,
                "policy_version": observed["policy_version"],
            }
            emit(
                HarnessEvent(
                    task.run_id,
                    HarnessEventType.TOOL_RESULT,
                    {
                        "id": "e2b-policy-execution",
                        "success": True,
                        "decision_digest": observed["decision_digest"],
                    },
                )
            )
            return AdapterOutcome(
                final_response=json.dumps(attestation, sort_keys=True),
                usage={"steps": 1, "input_tokens": 0, "output_tokens": 0},
                cost_usd=None,
                checkpoint={"sandbox_attestation": attestation},
                exit_code=0,
            )
        except Exception as exc:
            return AdapterOutcome(
                error_code="sandbox_execution_failed",
                error=(
                    f"{type(exc).__name__}: governed E2B execution failed; "
                    "credentials and provider request details were not retained."
                ),
                remediation=(
                    "Verify E2B access, package compatibility, quota, and the "
                    "egress-disabled sandbox policy, then create a new proposal."
                ),
                exit_code=1,
            )
        finally:
            if provider is not None:
                try:
                    provider.close()
                    terminated = True
                finally:
                    if terminated:
                        with self._lock:
                            self.sessions_closed += 1
