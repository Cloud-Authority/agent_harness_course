"""Run turn 4 and turn 5 in genuinely separate Python processes."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

COURSE = Path(__file__).resolve().parents[2]


def worker(build: str, phase: int) -> None:
    if build == "custom":
        sys.path.insert(0, str(COURSE / "part_1/custom_harness/appbook"))
        from backend.core.agent import get_graph
        from backend.core.memory import memory_provider
        if phase == 1:
            out = get_graph().run("Which regions are most profitable this quarter — and don't show me Accessories again.", "restart-proof")
        else:
            out = get_graph().run("Morning brief.", "restart-proof-after", bypass_cache=True)
        exclusions = memory_provider.exclusions()
    else:
        sys.path.insert(0, str(COURSE / "part_1/harness_done_for_you/memorizz/assistant/appbook"))
        from backend.core.agent import get_agent
        if phase == 1:
            out = get_agent().run("Which regions are most profitable this quarter — and don't show me Accessories again.", "restart-proof")
        else:
            out = get_agent().run("Morning brief.", "restart-proof-after")
        exclusions = get_agent().memory.exclusions()
    print(json.dumps({"phase": phase, "pid": os.getpid(), "answer": out["answer"],
                      "exclusions": exclusions,
                      "suppressed": [row.get("po_id") for row in out["data"].get("suppressed", [])],
                      "trace": out["trace"]}))


def parent(build: str) -> None:
    results = []
    for phase in (1, 2):
        proc = subprocess.run([sys.executable, __file__, "--build", build, "--worker", str(phase)],
                              cwd=COURSE, text=True, capture_output=True, check=True)
        results.append(json.loads(proc.stdout))
    assert results[0]["pid"] != results[1]["pid"]
    assert "Accessories" in results[0]["exclusions"]
    assert "Accessories" in results[1]["exclusions"]
    assert "Accessories" not in results[1]["answer"]
    assert "PO-BER-THC-OPEN" in results[1]["suppressed"]
    print(json.dumps({"build": build, "different_processes": True, "phases": results}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", choices=("memorizz", "custom"), default="custom")
    parser.add_argument("--worker", type=int, choices=(1, 2))
    args = parser.parse_args()
    worker(args.build, args.worker) if args.worker else parent(args.build)
