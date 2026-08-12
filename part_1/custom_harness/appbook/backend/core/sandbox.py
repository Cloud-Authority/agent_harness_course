"""Sandbox boundary: deterministic local mirror and fail-closed live E2B runs."""
from __future__ import annotations

import html
import json
from collections import defaultdict
from typing import Any

from backend.config import settings


def stock_chart(rows: list[dict[str, Any]]) -> str:
    """Local teaching mirror for the fixed stock-to-SVG operation."""
    sizes = ["XXS", "XS", "S", "M", "L", "XL", "XXL"]
    totals = defaultdict(int)
    for row in rows:
        totals[row["size"]] += int(row["on_hand"])
    width, height, pad = 760, 300, 48
    plot_h = height - 88
    maximum = max(totals.values()) or 1
    bar_w = (width - pad * 2) / len(sizes) - 12
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="ThermaCore stock by size">',
                '<rect width="100%" height="100%" rx="14" fill="#111827"/>',
                '<text x="48" y="30" fill="#f8fafc" font-family="system-ui" font-size="16" font-weight="700">ThermaCore · on-hand by size, all regions</text>']
    for i, size in enumerate(sizes):
        value = totals[size]
        h = plot_h * value / maximum
        x = pad + i * ((width - pad * 2) / len(sizes)) + 6
        y = height - 48 - h
        colour = "#f43f5e" if size in {"M", "L"} else "#38bdf8"
        elements.extend([f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="5" fill="{colour}"/>',
                         f'<text x="{x + bar_w/2:.1f}" y="{y-7:.1f}" fill="#e2e8f0" text-anchor="middle" font-family="monospace" font-size="12">{value}</text>',
                         f'<text x="{x + bar_w/2:.1f}" y="{height-24}" fill="#94a3b8" text-anchor="middle" font-family="system-ui" font-size="12">{html.escape(size)}</text>'])
    elements.append('</svg>')
    return "".join(elements)


def run_python_in_e2b(
    session_id: str,
    code: str,
    artifact_path: str = "/tool_out/result.json",
) -> dict[str, Any]:
    """Execute generated Python only in E2B and compact large output to ScratchFS."""
    if not settings.live:
        raise RuntimeError("Generated Python is disabled in local mode; start ERPA_MODE=live to use E2B")
    if not settings.e2b_api_key:
        raise RuntimeError("E2B_API_KEY is required; there is no host execution fallback")

    from e2b_code_interpreter import Sandbox
    from backend.core.scratchfs import ScratchFS

    sandbox = Sandbox.create(api_key=settings.e2b_api_key, timeout=120)
    try:
        execution = sandbox.run_code(code)
        stdout = "\n".join(str(item) for item in execution.logs.stdout)
        stderr = "\n".join(str(item) for item in execution.logs.stderr)
        payload = json.loads(execution.to_json())
        payload.update({"provider": "e2b", "stdout": stdout, "stderr": stderr})
    finally:
        sandbox.kill()
    serialised = json.dumps(payload, default=str, separators=(",", ":"))
    if len(serialised) > settings.sandbox_output_limit:
        pointer = ScratchFS(session_id).write(artifact_path, serialised)
        return {
            "provider": "e2b",
            "file_pointer": pointer["path"],
            "preview": serialised[:800],
            "stdout": stdout[:1200],
            "stderr": stderr[:1200],
        }
    return payload


def e2b_stock_chart(session_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Render the stock chart in E2B and persist the SVG in Oracle ScratchFS."""
    compact_rows = [{"size": row["size"], "on_hand": int(row["on_hand"])} for row in rows]
    code = f'''import html
from collections import defaultdict
rows = {json.dumps(compact_rows)}
sizes = ["XXS","XS","S","M","L","XL","XXL"]
totals = defaultdict(int)
for row in rows:
    totals[row["size"]] += int(row["on_hand"])
width, height, pad = 760, 300, 48
plot_h = height - 88
maximum = max(totals.values()) or 1
bar_w = (width - pad * 2) / len(sizes) - 12
parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {{width}} {{height}}" role="img" aria-label="ThermaCore stock by size">', '<rect width="100%" height="100%" rx="14" fill="#111827"/>', '<text x="48" y="30" fill="#f8fafc" font-family="system-ui" font-size="16" font-weight="700">ThermaCore · on-hand by size, all regions</text>']
for i, size in enumerate(sizes):
    value = totals[size]
    h = plot_h * value / maximum
    x = pad + i * ((width - pad * 2) / len(sizes)) + 6
    y = height - 48 - h
    colour = "#f43f5e" if size in {{"M","L"}} else "#38bdf8"
    parts += [f'<rect x="{{x:.1f}}" y="{{y:.1f}}" width="{{bar_w:.1f}}" height="{{h:.1f}}" rx="5" fill="{{colour}}"/>', f'<text x="{{x+bar_w/2:.1f}}" y="{{y-7:.1f}}" fill="#e2e8f0" text-anchor="middle" font-family="monospace" font-size="12">{{value}}</text>', f'<text x="{{x+bar_w/2:.1f}}" y="{{height-24}}" fill="#94a3b8" text-anchor="middle" font-family="system-ui" font-size="12">{{html.escape(size)}}</text>']
parts.append('</svg>')
print(''.join(parts))
'''
    result = run_python_in_e2b(session_id, code, "/tool_out/thermacore-chart-run.json")
    svg = str(result.get("stdout", "")).strip()
    if "<svg" not in svg:
        raise RuntimeError(f"E2B did not produce the expected SVG: {result.get('stderr') or result.get('preview')}")
    from backend.core.scratchfs import ScratchFS

    pointer = ScratchFS(session_id).write("/tool_out/thermacore-stock.svg", svg)
    return {"provider": "e2b", "chart_svg": svg, "file_pointer": pointer["path"]}
