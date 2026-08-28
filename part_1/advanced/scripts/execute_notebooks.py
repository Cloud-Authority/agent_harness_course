"""Execute and inspect advanced notebooks with explicit execution profiles.

The default offline profile is intentionally incapable of making provider calls. It
executes the two notebooks that have offline teaching paths and performs source
compilation on the three live-only notebooks. Named live profiles require the
corresponding provider credentials in the environment.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import secrets
import sys
import tempfile
from contextlib import contextmanager
from getpass import getpass
from pathlib import Path
from typing import Any

import nbformat
from nbclient import NotebookClient
from dotenv import load_dotenv


ADVANCED = Path(__file__).resolve().parents[1]
COURSE_ROOT = ADVANCED.parents[1]
load_dotenv(COURSE_ROOT / ".env", override=False)
NOTEBOOKS = [
    ADVANCED / "workflow/notebook/advanced_durable_workflow.ipynb",
    ADVANCED / "deep_research/notebook/advanced_deep_research.ipynb",
    ADVANCED / "metaharness/notebook/advanced_metaharness.ipynb",
    ADVANCED / "metaharness/notebook/advanced_fair_harness_evaluation.ipynb",
    ADVANCED / "total_recall/notebook/advanced_total_recall_ontology.ipynb",
]
LIVE_ONLY_NOTEBOOKS = {
    ADVANCED / "deep_research/notebook/advanced_deep_research.ipynb",
    ADVANCED / "metaharness/notebook/advanced_metaharness.ipynb",
    ADVANCED / "total_recall/notebook/advanced_total_recall_ontology.ipynb",
}
OFFLINE_ENVIRONMENT = {
    "ADVANCED_BACKEND": "memory",
    "ADVANCED_SEMANTIC_BACKEND": "hash",
    "ADVANCED_RESEARCH_SOURCE": "fixture",
    "ADVANCED_USE_MODEL_SYNTHESIS": "false",
    "ADVANCED_NOTEBOOK_LIVE": "0",
    "ADVANCED_SANDBOX_LIVE": "0",
    "ADVANCED_EVALUATION_LIVE": "0",
    "OPENAI_API_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "DEEPSEEK_API_KEY": "",
    "TAVILY_API_KEY": "",
    "E2B_API_KEY": "",
}
LIVE_ORACLE_WORKFLOW_ENVIRONMENT = {
    "ADVANCED_BACKEND": "oracle",
    "ADVANCED_SEMANTIC_BACKEND": "hash",
    "ADVANCED_EMBEDDING_DIMENSIONS": "1536",
    "ADVANCED_NOTEBOOK_LIVE": "1",
    "ADVANCED_SANDBOX_LIVE": "0",
    "ADVANCED_AGENT_MEMORY_SEARCH_STRATEGY": "keyword",
    "ADVANCED_AGENT_MEMORY_STORE_ID": "harness_kw",
    "ADVANCED_USE_MODEL_SYNTHESIS": "false",
    "OPENAI_API_KEY": "",
    "E2B_API_KEY": "",
}
SECRET_MARKERS = (
    "sk-" + "proj-",
    "sk-" + "ant-api",
    "tvly" + "-",
    "e2b" + "_aa",
)


def _sanitize_text(value: str) -> str:
    sanitized = value.replace(str(COURSE_ROOT), "<course-root>")
    sanitized = re.sub(
        r"/(?:private/)?(?:tmp|var/folders)/[^\s'\",}\]]+",
        "<temporary-path>",
        sanitized,
    )
    return sanitized


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    return value


def _usable_credential(value: str) -> bool:
    """Reject empty values and obvious course placeholders."""

    normalized = str(value or "").strip()
    return len(normalized) >= 20 and "replace" not in normalized.lower()


def _inspect(notebook: Any) -> dict[str, Any]:
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    errors = []
    output_count = 0
    rendered = []
    for index, cell in enumerate(notebook.cells):
        if cell.cell_type != "code":
            continue
        output_count += len(cell.outputs)
        for output in cell.outputs:
            rendered.append(json.dumps(output, default=str))
            output_type = (
                output.get("output_type")
                if isinstance(output, dict)
                else output.output_type
            )
            if output_type == "error":
                errors.append(
                    {
                        "cell": index,
                        "name": output.get("ename"),
                        "message": output.get("evalue"),
                    }
                )
    combined = "\n".join(rendered)
    leaked_markers = [marker for marker in SECRET_MARKERS if marker in combined]
    return {
        "code_cells": len(code_cells),
        "executed_code_cells": sum(
            cell.execution_count is not None for cell in code_cells
        ),
        "outputs": output_count,
        "errors": errors,
        "secret_markers": leaked_markers,
    }


def execute(path: Path, *, kernel_name: str, timeout: int) -> dict[str, Any]:
    notebook = nbformat.read(path, as_version=4)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            cell.execution_count = None
            cell.outputs = []
    client = NotebookClient(
        notebook,
        kernel_name=kernel_name,
        timeout=timeout,
        allow_errors=False,
        resources={"metadata": {"path": str(COURSE_ROOT)}},
        record_timing=True,
    )
    client.execute()
    for cell in notebook.cells:
        if cell.cell_type == "code":
            cell.outputs = [
                nbformat.from_dict(_sanitize(output)) for output in cell.outputs
            ]
    inspection = _inspect(notebook)
    if inspection["errors"]:
        raise RuntimeError(f"Notebook produced errors: {inspection['errors']}")
    if inspection["code_cells"] != inspection["executed_code_cells"]:
        raise RuntimeError("At least one code cell did not execute")
    if inspection["secret_markers"]:
        raise RuntimeError(
            f"Notebook output contains a credential marker: {inspection['secret_markers']}"
        )
    nbformat.write(notebook, path)
    persisted = _inspect(nbformat.read(path, as_version=4))
    if persisted["errors"] or persisted["secret_markers"]:
        raise RuntimeError(
            "Persisted notebook failed output validation: "
            f"errors={persisted['errors']}, secret_markers={persisted['secret_markers']}"
        )
    return {"notebook": str(path.relative_to(COURSE_ROOT)), **persisted}


def validate_live_only_source(path: Path) -> dict[str, Any]:
    """Compile every code cell without impersonating a successful live run."""

    notebook = nbformat.read(path, as_version=4)
    compiled = 0
    for index, cell in enumerate(notebook.cells):
        if cell.cell_type != "code":
            continue
        compile(
            cell.source,
            f"{path}#cell-{index}",
            "exec",
            flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
        )
        compiled += 1
    inspection = _inspect(notebook)
    source = "\n".join(cell.source for cell in notebook.cells)
    leaked_markers = [marker for marker in SECRET_MARKERS if marker in source]
    if inspection["errors"] or inspection["secret_markers"] or leaked_markers:
        raise RuntimeError(
            "Live-only notebook failed static validation: "
            f"errors={inspection['errors']}, "
            f"output_markers={inspection['secret_markers']}, "
            f"source_markers={leaked_markers}"
        )
    return {
        "notebook": str(path.relative_to(COURSE_ROOT)),
        "validation": "static-live-only",
        "code_cells": inspection["code_cells"],
        "compiled_code_cells": compiled,
        "executed_code_cells": inspection["executed_code_cells"],
        "outputs": inspection["outputs"],
        "errors": [],
        "secret_markers": [],
    }


@contextmanager
def _course_kernel(requested_name: str | None):
    """Use a caller-selected kernel or create one bound to this interpreter."""

    if requested_name:
        yield requested_name
        return
    previous = os.environ.get("JUPYTER_PATH")
    with tempfile.TemporaryDirectory(prefix="advanced-course-kernel-") as directory:
        data_dir = Path(directory) / "share" / "jupyter"
        spec_dir = data_dir / "kernels" / "advanced-harness-course"
        spec_dir.mkdir(parents=True)
        (spec_dir / "kernel.json").write_text(
            json.dumps(
                {
                    "argv": [
                        sys.executable,
                        "-m",
                        "ipykernel_launcher",
                        "-f",
                        "{connection_file}",
                    ],
                    "display_name": "Python 3 (advanced harness course)",
                    "language": "python",
                }
            ),
            encoding="utf-8",
        )
        os.environ["JUPYTER_PATH"] = (
            str(data_dir) if not previous else f"{data_dir}{os.pathsep}{previous}"
        )
        try:
            yield "advanced-harness-course"
        finally:
            if previous is None:
                os.environ.pop("JUPYTER_PATH", None)
            else:
                os.environ["JUPYTER_PATH"] = previous


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--kernel",
        default=None,
        help="Existing kernelspec name. Default: a temporary kernel using this Python.",
    )
    parser.add_argument(
        "--notebook",
        action="append",
        choices=[path.name for path in NOTEBOOKS],
        help="Execute only this notebook filename; repeat to select more than one.",
    )
    parser.add_argument(
        "--profile",
        choices=(
            "offline",
            "live-oracle-workflow",
            "live-oracle-total-recall",
            "live-deep-research",
            "live-metaharness",
        ),
        default="offline",
        help="Execution profile. Each live profile is restricted to its named lab.",
    )
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--query",
        default=(
            "Using the Oracle incident evidence, explain the failure, recommend next "
            "actions, and separate supported facts from inference. Cite source IDs."
        ),
        help="Live MetaHarness query; ignored by other profiles.",
    )
    parser.add_argument(
        "--harness",
        choices=(
            "auto",
            "openai-live",
            "anthropic-live",
            "deepseek-live",
            "both",
            "all",
        ),
        default="auto",
        help=(
            "Live MetaHarness selection. 'both' runs Anthropic then OpenAI; "
            "'all' also runs DeepSeek."
        ),
    )
    parser.add_argument(
        "--confirm-live-metaharness",
        action="store_true",
        help=(
            "Acknowledge paid calls and that the minimized Oracle incident fields "
            "printed by the notebook may be sent to the selected provider."
        ),
    )
    args = parser.parse_args()
    if args.profile == "offline":
        os.environ.update(OFFLINE_ENVIRONMENT)
    elif args.profile == "live-oracle-workflow":
        if args.notebook != ["advanced_durable_workflow.ipynb"]:
            parser.error(
                "--profile live-oracle-workflow requires exactly "
                "--notebook advanced_durable_workflow.ipynb"
            )
        os.environ.update(LIVE_ORACLE_WORKFLOW_ENVIRONMENT)
    elif args.profile == "live-oracle-total-recall":
        if args.notebook != ["advanced_total_recall_ontology.ipynb"]:
            parser.error(
                "--profile live-oracle-total-recall requires exactly "
                "--notebook advanced_total_recall_ontology.ipynb"
            )
        if not (
            os.environ.get("ORA_AGENT_PWD", "").strip()
            or os.environ.get("ADVANCED_ORA_PASSWORD", "").strip()
        ):
            parser.error(
                "live-oracle-total-recall requires ORA_AGENT_PWD or "
                "ADVANCED_ORA_PASSWORD"
            )
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            parser.error(
                "live-oracle-total-recall requires OPENAI_API_KEY for GPT-5.5"
            )
    elif args.profile == "live-deep-research":
        if args.notebook != ["advanced_deep_research.ipynb"]:
            parser.error(
                "--profile live-deep-research requires exactly "
                "--notebook advanced_deep_research.ipynb"
            )
        missing = [
            name
            for name in ("OPENAI_API_KEY", "TAVILY_API_KEY", "E2B_API_KEY")
            if not os.environ.get(name, "").strip()
        ]
        if not (
            os.environ.get("ADVANCED_ORA_PASSWORD", "").strip()
            or os.environ.get("ORA_AGENT_PWD", "").strip()
        ):
            missing.append("ADVANCED_ORA_PASSWORD or ORA_AGENT_PWD")
        if missing:
            parser.error(
                "live-deep-research requires environment credentials: "
                + ", ".join(missing)
            )
        if os.environ.get("ADVANCED_RESEARCH_CONFIRMATION", "").strip() != (
            "RUN LIVE DEEP RESEARCH"
        ):
            parser.error(
                "set ADVANCED_RESEARCH_CONFIRMATION='RUN LIVE DEEP RESEARCH' "
                "to authorize network and paid provider calls"
            )
    else:
        if args.notebook != ["advanced_metaharness.ipynb"]:
            parser.error(
                "--profile live-metaharness requires exactly "
                "--notebook advanced_metaharness.ipynb"
            )
        if not args.confirm_live_metaharness:
            parser.error(
                "--profile live-metaharness requires --confirm-live-metaharness"
            )
        if not (
            os.environ.get("ADVANCED_ORA_PASSWORD", "").strip()
            or os.environ.get("ORA_AGENT_PWD", "").strip()
        ):
            parser.error(
                "live-metaharness requires ADVANCED_ORA_PASSWORD or ORA_AGENT_PWD"
            )
        if not _usable_credential(os.environ.get("OPENAI_API_KEY", "")):
            os.environ["OPENAI_API_KEY"] = getpass(
                "OpenAI key for live embeddings and the OpenAI harness (hidden): "
            ).strip()
        if not _usable_credential(os.environ.get("OPENAI_API_KEY", "")):
            parser.error("live-metaharness requires a usable OPENAI_API_KEY")
        if args.harness in {"anthropic-live", "both", "all"}:
            if not _usable_credential(os.environ.get("ANTHROPIC_API_KEY", "")):
                os.environ["ANTHROPIC_API_KEY"] = getpass(
                    "Anthropic key for the live Anthropic harness (hidden): "
                ).strip()
            if not _usable_credential(os.environ.get("ANTHROPIC_API_KEY", "")):
                parser.error("the selected harness requires a usable ANTHROPIC_API_KEY")
        if args.harness in {"deepseek-live", "all"}:
            if not _usable_credential(os.environ.get("DEEPSEEK_API_KEY", "")):
                os.environ["DEEPSEEK_API_KEY"] = getpass(
                    "DeepSeek key for the live DeepSeek harness (hidden): "
                ).strip()
            if not _usable_credential(os.environ.get("DEEPSEEK_API_KEY", "")):
                parser.error("the selected harness requires a usable DEEPSEEK_API_KEY")
        os.environ["ADVANCED_BACKEND"] = "oracle"
        os.environ["ADVANCED_SEMANTIC_BACKEND"] = "openai"
        os.environ["ADVANCED_METAHARNESS_QUERY"] = args.query.strip()
        os.environ["ADVANCED_METAHARNESS_EXTERNAL_CONFIRMATION"] = (
            "SEND MINIMIZED ORACLE INCIDENT EVIDENCE"
        )
    selected = (
        NOTEBOOKS
        if not args.notebook
        else [path for path in NOTEBOOKS if path.name in set(args.notebook)]
    )
    with _course_kernel(args.kernel) as kernel_name:
        results = []
        execution_harnesses = (
            ["deepseek-live", "anthropic-live", "openai-live"]
            if args.profile == "live-metaharness" and args.harness == "all"
            else
            ["anthropic-live", "openai-live"]
            if args.profile == "live-metaharness" and args.harness == "both"
            else [args.harness]
            if args.profile == "live-metaharness"
            else [None]
        )
        for selected_harness in execution_harnesses:
            if selected_harness is not None:
                os.environ["ADVANCED_METAHARNESS_HARNESS"] = selected_harness
                os.environ["ADVANCED_METAHARNESS_THREAD_ID"] = (
                    f"notebook-live-{selected_harness}-{secrets.token_hex(4)}"
                )
            for path in selected:
                if args.profile == "offline" and path in LIVE_ONLY_NOTEBOOKS:
                    result = validate_live_only_source(path)
                else:
                    result = execute(
                        path,
                        kernel_name=kernel_name,
                        timeout=args.timeout,
                    )
                if selected_harness is not None:
                    result["requested_harness"] = selected_harness
                results.append(result)
    print(json.dumps({"profile": args.profile, "notebooks": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
