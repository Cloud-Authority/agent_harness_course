"""Build standalone teaching notebooks from harness modules.

A notebook is a list of parts. A part has a title, its markdown, and cells.
A code cell can be literal source, or the source of named definitions lifted
from a module with ``lift("module", "name", ...)``. Lifted code drops its
import lines, so the notebook needs one imports cell of its own, and every
definition calls the others by bare name. Mermaid diagrams in markdown are
rendered to PNG and attached, so they show in every viewer.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import nbformat

ADVANCED = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADVANCED / "tools")) if (ADVANCED / "tools").exists() else None


def lift(path: Path, *names: str) -> str:
    """The source of top-level definitions and assignments, in the order asked for."""
    tree = ast.parse(path.read_text())
    source = path.read_text().splitlines()
    found: dict[str, str] = {}
    for node in tree.body:
        keys = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            keys = [node.name]
        elif isinstance(node, ast.Assign):
            keys = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            keys = [node.target.id]
        for key in keys:
            start = node.lineno - 1
            if getattr(node, "decorator_list", None):
                start = min(d.lineno for d in node.decorator_list) - 1
            found[key] = "\n".join(source[start:node.end_lineno])
    missing = [n for n in names if n not in found]
    if missing:
        raise KeyError(f"{path.name} has no {missing}")
    return "\n\n\n".join(found[n] for n in names)


def code(source: str) -> dict:
    return {"kind": "code", "source": source.strip("\n")}


def md(text: str) -> dict:
    return {"kind": "markdown", "source": text.strip("\n")}


def part(title: str, intro: str, *cells: dict, star: bool = False) -> dict:
    return {"title": title, "intro": intro.strip("\n"), "cells": list(cells), "star": star}


def render_mermaid(diagram: str, out_dir: Path, name: str) -> Path | None:
    """Mermaid to PNG with the Mermaid CLI, cached by content."""
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(diagram.encode()).hexdigest()[:10]
    png = out_dir / f"{name}-{digest}.png"
    if png.exists():
        return png
    for old in out_dir.glob(f"{name}-*.png"):
        old.unlink()
    (out_dir / f"{name}.mmd").write_text(diagram)
    mmdc = ADVANCED / ".tools" / "node_modules" / ".bin" / "mmdc"
    command = [str(mmdc) if mmdc.exists() else "mmdc", "-i", str(out_dir / f"{name}.mmd"), "-o", str(png),
               "-b", "white", "-s", "1.25"]
    config = out_dir / ".mermaid-config.json"
    config.write_text(json.dumps({"theme": "neutral", "flowchart": {"useMaxWidth": False},
                                  "sequence": {"useMaxWidth": False}}))
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    puppeteer = out_dir / ".puppeteer.json"
    puppeteer.write_text(json.dumps({"args": ["--no-sandbox"], **({"executablePath": chrome} if Path(chrome).exists() else {})}))
    command += ["-c", str(config), "-p", str(puppeteer)]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode != 0 or not png.exists():
        print("mermaid failed for", name, done.stderr[-300:])
        return None
    return png


def markdown_cell(text: str, diagrams_dir: Path, name: str) -> nbformat.NotebookNode:
    """Mermaid blocks become attached images; the source stays beside the notebook."""
    attachments = {}
    counter = [0]

    def replace(match: re.Match) -> str:
        counter[0] += 1
        png = render_mermaid(match.group(1).strip(), diagrams_dir, f"{name}-{counter[0]}")
        if png is None:
            return match.group(0)
        attachments[png.name] = {"image/png": base64.b64encode(png.read_bytes()).decode()}
        return f"![{name}](attachment:{png.name})"

    body = re.sub(r"```mermaid\n(.*?)```", replace, text, flags=re.S)
    cell = nbformat.v4.new_markdown_cell(body)
    if attachments:
        cell["attachments"] = attachments
    return cell


def build(title: str, lead: str, parts: list[dict], out: Path, diagrams_dir: Path, closing: list[dict] = ()) -> Path:
    """Numbered parts, N.M sections from cell titles, a star on live sections, a contents list."""
    cells = [markdown_cell(f"# {title}\n\n{lead}", diagrams_dir, "lead")]
    contents = []
    for number, section in enumerate(parts, start=1):
        star = " ⭐" if section["star"] else ""
        contents.append(f"- Part {number}: {section['title']}{star}")
        cells.append(markdown_cell(f"## Part {number}: {section['title']}{star}\n\n{section['intro']}",
                                   diagrams_dir, f"part{number:02d}"))
        step = 0
        for cell in section["cells"]:
            if cell["kind"] == "markdown":
                step += 1
                cells.append(markdown_cell(re.sub(r"^### ", f"### {number}.{step} ", cell["source"], count=1),
                                           diagrams_dir, f"part{number:02d}-{step}"))
            else:
                node = nbformat.v4.new_code_cell(cell["source"])
                cells.append(node)
    for cell in closing:
        cells.append(markdown_cell(cell["source"], diagrams_dir, "closing") if cell["kind"] == "markdown"
                     else nbformat.v4.new_code_cell(cell["source"]))
    cells.insert(1, markdown_cell("## Contents\n\n" + "\n".join(contents) +
                                  "\n\nA star marks a part to show live; the rest is read.", diagrams_dir, "contents"))
    notebook = nbformat.v4.new_notebook(cells=cells)
    notebook.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    notebook.metadata["language_info"] = {"name": "python"}
    out.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, out)
    return out
