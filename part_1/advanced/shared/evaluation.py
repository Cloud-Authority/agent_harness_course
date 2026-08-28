"""Fair MetaHarness evaluation helpers for the advanced course.

The protocol is adapted from the design lessons in MemoRizz example 06, but this
module imports only the installed PyPI distribution.  Its default execution is a
deterministic mechanics audit.  Frontier-model calls remain a separately approved
smoke experiment and never become a leaderboard claim.
"""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import version
from typing import Any


TASK_SUITE = [
    {
        "task_id": "authorization-expiry",
        "family": "policy repair",
        "risk": "ordinary",
        "hidden_checks": [
            "expired approval rejected",
            "timezone boundary covered",
            "host verification passes",
        ],
    },
    {
        "task_id": "tenant-isolation",
        "family": "security repair",
        "risk": "high",
        "hidden_checks": [
            "cross-tenant read blocked",
            "cross-tenant write blocked",
            "negative test included",
        ],
    },
    {
        "task_id": "approval-replay",
        "family": "durability repair",
        "risk": "high",
        "hidden_checks": [
            "exact argument hash bound",
            "approval consumed once",
            "workspace tamper invalidates proposal",
        ],
    },
    {
        "task_id": "sandbox-egress",
        "family": "sandbox policy",
        "risk": "high",
        "hidden_checks": [
            "sandbox egress disabled",
            "credentials not forwarded",
            "sandbox terminated in finally",
        ],
    },
]

STRATEGIES = [
    {
        "name": "direct_gpt55",
        "interface": "direct",
        "call_policy": "exactly_one_gpt55",
    },
    {
        "name": "memorizz_gpt55",
        "interface": "wrapper",
        "call_policy": "exactly_one_gpt55",
    },
    {
        "name": "direct_opus5",
        "interface": "direct",
        "call_policy": "exactly_one_opus5",
    },
    {
        "name": "memorizz_opus5",
        "interface": "wrapper",
        "call_policy": "exactly_one_opus5",
    },
    {
        "name": "panel_always",
        "interface": "panel",
        "call_policy": "one_gpt55_and_one_opus5",
    },
    {
        "name": "panel_risk_routed",
        "interface": "panel",
        "call_policy": "one_preregistered_model_per_task",
    },
]

PROVIDERS = ["filesystem", "oracle"]


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


def stable_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def protocol_manifest(*, repeats: int = 2, seed: int = 20260825) -> dict[str, Any]:
    """Freeze a 2-provider × 6-strategy factorial before paid execution."""

    arms = {
        f"{strategy['name']}__{provider}": {
            **strategy,
            "provider": provider,
            "models": (
                ["gpt-5.5", "claude-opus-5"]
                if strategy["interface"] == "panel"
                else [
                    "gpt-5.5"
                    if "gpt55" in strategy["name"]
                    else "claude-opus-5"
                ]
            ),
        }
        for provider in PROVIDERS
        for strategy in STRATEGIES
    }
    ordered_arms = sorted(arms)
    execution_orders = [ordered_arms, list(reversed(ordered_arms))]
    manifest: dict[str, Any] = {
        "schema_version": "advanced.metaharness.protocol.v1",
        "protocol": "paired_factorial_2x6_v1",
        "industry_use_case": (
            "A regulated fintech platform chooses a review strategy for "
            "authorization-policy repairs."
        ),
        "models": {"openai": "gpt-5.5", "anthropic": "claude-opus-5"},
        "providers": PROVIDERS,
        "strategies": STRATEGIES,
        "arms": arms,
        "task_suite": TASK_SUITE,
        "repeats": repeats,
        "seed": seed,
        "execution_orders": execution_orders[:repeats],
        "primary_metric": "micro pass rate over task-native hidden checks",
        "secondary_metrics": [
            "fully correct tasks",
            "wall latency",
            "provider-reported tokens",
            "measured cost",
            "harness calls",
        ],
        "judge_policy": (
            "Task-native deterministic checks are primary. Any identity-blind LLM "
            "judge is diagnostic and fails closed on rubric or scale violations."
        ),
        "estimands": {
            "wrapper_overhead_gpt55": "memorizz_gpt55 - direct_gpt55",
            "wrapper_overhead_opus5": "memorizz_opus5 - direct_opus5",
            "mandatory_coordination_value": "panel_always - memorizz_single",
            "routing_value": "panel_risk_routed - panel_always",
            "provider_sensitivity": "oracle - filesystem for the same strategy",
        },
        "claim_boundary": (
            "Independent tasks are the unit of inference. Repeats of one task are "
            "not independent samples, and a smoke run cannot name a general winner."
        ),
        "winner_allowed": False,
        "paper_comparable": False,
        "package_versions": {
            "memorizz": version("memorizz"),
            "openai": version("openai"),
            "anthropic": version("anthropic"),
        },
    }
    manifest["protocol_fingerprint"] = stable_hash(manifest)
    return manifest


def source_notebook_lessons() -> dict[str, Any]:
    """Record which methodological lessons were adapted from example 06."""

    return {
        "reference": "memorizz/examples/metaharness/06_fair_harness_comparison_results.ipynb",
        "adapted_controls": [
            "freeze protocol and hashes before looking at new paid results",
            "define estimands instead of comparing every row informally",
            "separate wrapper, coordination, routing, and provider effects",
            "counterbalance execution order",
            "preflight context and workspace parity",
            "count every attempted provider and judge call",
            "make deterministic task checks primary",
            "invalidate a scalar judge that violates its rubric",
            "treat tasks, not reruns, as the sample unit",
            "set winner_allowed=false for a bounded smoke experiment",
        ],
        "runtime_import_policy": (
            "The course does not import that checkout or its eval package. All "
            "MemoRizz runtime objects come from the installed PyPI wheel."
        ),
    }


def _row(name: str, results: list[dict[str, Any]], *, topology: str) -> dict[str, Any]:
    context_fingerprints = {
        (item.get("context_pack") or {}).get("content_fingerprint")
        for item in results
        if (item.get("context_pack") or {}).get("content_fingerprint")
    }
    workspace_fingerprints = {
        item.get("workspace_fingerprint_before")
        for item in results
        if item.get("workspace_fingerprint_before")
    }
    checks = {
        "all_succeeded": all(item.get("status") == "succeeded" for item in results),
        "all_host_verified": all(bool(item.get("verified")) for item in results),
        "all_memory_grounded": all(
            bool((item.get("context_pack") or {}).get("source_ids"))
            for item in results
        ),
        "same_scoped_context": len(context_fingerprints) == 1,
        "same_workspace": len(workspace_fingerprints) == 1,
        "normalized_usage_present": all(
            isinstance(item.get("usage"), dict) and "steps" in item["usage"]
            for item in results
        ),
    }
    if topology != "single":
        checks["multiple_independent_harnesses"] = (
            len({item.get("harness") for item in results}) == len(results)
        )
    return {
        "strategy": name,
        "topology": topology,
        "harnesses": [item.get("harness") for item in results],
        "calls": len(results),
        "verified_calls": sum(bool(item.get("verified")) for item in results),
        "input_tokens": sum(int((item.get("usage") or {}).get("input_tokens") or 0) for item in results),
        "output_tokens": sum(int((item.get("usage") or {}).get("output_tokens") or 0) for item in results),
        "wall_latency_ms": sum(int(item.get("latency_ms") or 0) for item in results),
        "cost_usd": sum(float(item.get("cost_usd") or 0.0) for item in results),
        "control_checks": checks,
        "control_checks_passed": sum(bool(value) for value in checks.values()),
        "control_checks_total": len(checks),
    }


def mechanics_artifact(course: Any) -> dict[str, Any]:
    """Execute real MemoRizz contracts with deterministic, no-cost adapters."""

    single = course.run_grounded_review()["result"]
    team = course.run_review_team()
    comparison_results = list(team["comparison"]["results"])
    plan_results = list(team["serial_review_plan"])
    rows = [
        _row("grounded_single", [single], topology="single"),
        _row(
            "independent_review_pair",
            comparison_results,
            topology="parallel-comparison",
        ),
        _row("serial_adversarial_plan", plan_results, topology="serial-plan"),
    ]
    artifact: dict[str, Any] = {
        "schema_version": "advanced.metaharness.mechanics.v1",
        "execution_profile": "deterministic-no-network-control-plane-audit",
        "memorizz_version": version("memorizz"),
        "rows": rows,
        "validity_gates": {
            "all_rows_complete": len(rows) == 3,
            "all_calls_verified": all(
                row["verified_calls"] == row["calls"] for row in rows
            ),
            "all_rows_memory_grounded": all(
                row["control_checks"]["all_memory_grounded"] for row in rows
            ),
            "all_workspaces_stable": all(
                row["control_checks"]["same_workspace"] for row in rows
            ),
            "zero_model_calls": True,
            "zero_network_calls": True,
        },
        "paired_deltas": {
            "independent_pair_minus_single": {
                "calls": rows[1]["calls"] - rows[0]["calls"],
                "control_checks_passed": (
                    rows[1]["control_checks_passed"]
                    - rows[0]["control_checks_passed"]
                ),
                "wall_latency_ms": (
                    rows[1]["wall_latency_ms"] - rows[0]["wall_latency_ms"]
                ),
            },
            "serial_plan_minus_single": {
                "calls": rows[2]["calls"] - rows[0]["calls"],
                "control_checks_passed": (
                    rows[2]["control_checks_passed"]
                    - rows[0]["control_checks_passed"]
                ),
                "wall_latency_ms": (
                    rows[2]["wall_latency_ms"] - rows[0]["wall_latency_ms"]
                ),
            },
        },
        "winner_allowed": False,
        "claim_boundary": (
            "These deterministic rows validate MemoRizz routing, scoped context, "
            "normalized accounting, topology, and host verification. They do not "
            "measure GPT-5.5 or Claude Opus 5 quality."
        ),
    }
    artifact["artifact_fingerprint"] = stable_hash(artifact)
    artifact["valid"] = all(artifact["validity_gates"].values())
    return artifact
