"""Embed the Mermaid diagrams of a notebook as images, so they display in every viewer.

Mermaid inside notebook markdown is drawn by JupyterLab 4.1 or newer, Notebook 7.1 or
newer, and GitHub. VS Code, Cursor, Colab and older Jupyter show the diagram's source
text instead. An embedded image displays everywhere.

For each markdown cell this tool finds the fenced ``mermaid`` blocks, renders each one
to a PNG, stores the PNG in the cell as an attachment, and replaces the block with a
markdown image. Code cells and saved outputs are not touched. The diagram source and
the image are also written to a ``diagrams`` folder beside the notebook, so a diagram
can be edited and rendered again.

Usage
-----
    python tools/notebook_diagrams.py path/to/notebook.ipynb [more.ipynb ...]

Requirements
------------
Node.js, the Mermaid command line tool and a Chrome or Chromium browser:

    npm install --global @mermaid-js/mermaid-cli

Environment variables
---------------------
MMDC     Path to the ``mmdc`` executable. Default: ``mmdc`` on the PATH.
CHROME   Path to the browser. Default: Google Chrome in its usual place on macOS,
         otherwise whatever Puppeteer finds.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import nbformat

FENCE = re.compile(r"```mermaid\n(.*?)```", re.S)
HEADING = re.compile(r"^#{1,4} (.+)$", re.M)
MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WIDE = 1000
CONFIG = {
    "theme": "base",
    "themeVariables": {
        "fontFamily": "Helvetica, Arial, sans-serif", "fontSize": "15px",
        "primaryColor": "#EAF1FB", "primaryBorderColor": "#2F5D9B", "primaryTextColor": "#17202A",
        "secondaryColor": "#FBF3E4", "secondaryBorderColor": "#A8741A", "secondaryTextColor": "#17202A",
        "tertiaryColor": "#F4F6F8", "tertiaryBorderColor": "#8A97A6", "tertiaryTextColor": "#17202A",
        "lineColor": "#44546A", "textColor": "#17202A", "clusterBkg": "#F7F9FC",
        "clusterBorder": "#8A97A6", "edgeLabelBackground": "#FFFFFF", "noteBkgColor": "#FBF3E4",
        "noteBorderColor": "#A8741A", "actorBkg": "#EAF1FB", "actorBorder": "#2F5D9B",
        "signalColor": "#44546A", "signalTextColor": "#17202A", "labelBoxBkgColor": "#EAF1FB"},
    "flowchart": {"htmlLabels": True, "curve": "basis", "padding": 12, "useMaxWidth": False},
    "sequence": {"mirrorActors": False, "actorMargin": 18, "width": 128, "height": 44,
                 "messageMargin": 28, "wrap": True, "useMaxWidth": False},
}
SCALE = 1.25


def tool() -> str:
    found = os.environ.get("MMDC") or shutil.which("mmdc")
    if not found:
        sys.exit("mmdc was not found. Install it with: npm install --global @mermaid-js/mermaid-cli")
    return found


def png_width(data: bytes) -> int:
    return struct.unpack(">I", data[16:20])[0]


def render(diagram: str, target: Path, settings: Path) -> bytes:
    """Render one diagram. It is rendered again only when its source changed."""
    source, image = target.with_suffix(".mmd"), target.with_suffix(".png")
    if not (image.exists() and source.exists() and source.read_text() == diagram):
        source.write_text(diagram)
        done = subprocess.run(
            [tool(), "-i", str(source), "-o", str(image), "-b", "white", "-s", str(SCALE),
             "-c", str(settings / "mermaid.json"), "-p", str(settings / "browser.json"), "-q"],
            capture_output=True, text=True)
        if done.returncode or not image.exists():
            source.unlink(missing_ok=True)
            sys.exit(f"Mermaid could not render {source.name}:\n{done.stdout}\n{done.stderr}")
    return image.read_bytes()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "diagram"


def embed(path: Path, settings: Path) -> dict:
    notebook = nbformat.read(path, as_version=4)
    folder = path.parent / "diagrams"
    heading, count, wide = path.stem, 0, []
    for cell in notebook.cells:
        if cell.cell_type != "markdown":
            continue
        attachments = dict(cell.get("attachments", {}))

        def place(match: re.Match) -> str:
            nonlocal count
            before = HEADING.findall(cell.source[:match.start()])
            title = re.sub(r"[*`_]", "", before[-1] if before else heading).strip()
            count += 1
            name = f"{path.stem}-{count:02d}-{slug(title)}"
            folder.mkdir(exist_ok=True)
            image = render(match.group(1), folder / name, settings)
            if png_width(image) / SCALE > WIDE:
                wide.append((name, round(png_width(image) / SCALE)))
            attachments[f"{name}.png"] = {"image/png": base64.b64encode(image).decode()}
            return f"![Diagram: {title}](attachment:{name}.png)"

        found = HEADING.findall(cell.source)
        cell.source = FENCE.sub(place, cell.source)
        heading = re.sub(r"[*`_]", "", found[-1]).strip() if found else heading
        if attachments:
            cell["attachments"] = attachments
    nbformat.validate(notebook)
    nbformat.write(notebook, path)
    return {"notebook": path.name, "diagrams_embedded": count, "wider_than_1000px": wide}


def main(paths: list[str]) -> None:
    if not paths:
        sys.exit(__doc__)
    with tempfile.TemporaryDirectory() as scratch:
        settings = Path(scratch)
        (settings / "mermaid.json").write_text(json.dumps(CONFIG))
        chrome = os.environ.get("CHROME") or (MAC_CHROME if Path(MAC_CHROME).exists() else "")
        browser = {"args": ["--no-sandbox"], **({"executablePath": chrome} if chrome else {})}
        (settings / "browser.json").write_text(json.dumps(browser))
        for path in paths:
            print(embed(Path(path), settings))


if __name__ == "__main__":
    main(sys.argv[1:])
