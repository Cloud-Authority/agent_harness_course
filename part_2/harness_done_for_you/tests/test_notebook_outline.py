"""The builder's outline: numbers, stars, contents and the live path are generated.

A person writes headings and markers. The builder numbers the sections, stars the
ones to show live, and writes the contents and the live path from the same
markers, so the three cannot drift apart. These tests use a small notebook made
up for the purpose.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

TRACK = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def parts():
    spec = importlib.util.spec_from_file_location("notebook_parts",
                                                  TRACK / "scripts" / "notebook_parts.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["notebook_parts"] = module
    spec.loader.exec_module(module)
    return module


def small(parts, minutes=(15, 16)):
    md, code = parts.md, parts.code
    return [
        md("# A title\n\nWhat this is."),
        md(parts.NAVIGATION),
        md("## Before the parts\n\nNot numbered."),
        md("# Part 1 · First\n<!-- part: What the first part covers -->\n\n## Setting up\n"
           "<!-- key: setup -->\n\nText."),
        code("x = 1"),
        md(f"## Showing it\n<!-- live: {minutes[0]} | What to show here | [[setup]], then this "
           "section -->\n\n```python\n## not a heading\n```"),
        code("print(x)"),
        md("### Takeaways\n\n- One.\n- Two.\n- Three."),
        md("# Part 2 · Second\n<!-- part: What the second part covers -->\n\n## More\n"
           f"<!-- live: {minutes[1]} | What to show there | This section -->\n\nSee [[setup]]."),
        code("y = 2"),
        md("### Takeaways\n\n- One.\n- Two.\n- Three."),
    ]


def test_sections_get_numbers_and_live_sections_get_a_star(parts):
    cells, found, live = parts.assemble(small(parts), "About this notebook.")
    text = "\n".join(cell["source"] for cell in cells if cell["kind"] == "markdown")
    assert "## 1.1 · Setting up" in text and f"## 1.2 · {parts.STAR} Showing it" in text
    assert f"## 2.1 · {parts.STAR} More" in text and "## Before the parts" in text
    assert "## Takeaways · Part 1" in text and "## Takeaways · Part 2" in text
    assert [(part["number"], part["sections"], part["stars"]) for part in found] == \
        [(1, 2, 1), (2, 1, 1)]
    assert [row["number"] for row in live] == ["1.2", "2.1"]


def test_markers_are_removed_and_references_become_numbers(parts):
    cells, _, live = parts.assemble(small(parts), "About this notebook.")
    text = "\n".join(cell["source"] for cell in cells if cell["kind"] == "markdown")
    assert "<!--" not in text and "[[" not in text
    assert "See 1.1." in text and live[0]["again"] == "1.1, then this section"
    assert "## not a heading" in text, "a line inside a code fence is left alone"


def test_the_guide_is_generated_from_the_same_markers(parts):
    cells, _, _ = parts.assemble(small(parts), "About this notebook.")
    use, contents, path = (cell["source"] for cell in cells[1:4])
    assert use.startswith("## How to use this notebook") and "About this notebook." in use
    assert "No sign-in is needed" in use and "about 31 minutes" in use
    assert f"| 1 | First | What the first part covers | {parts.STAR} |" in contents
    assert "| 1.2 · Showing it | What to show here | 15 | 1.1, then this section |" in path
    assert "Together they take about 31 minutes" in path


def test_a_finished_notebook_passes_the_checks(parts):
    cells, found, live = parts.assemble(small(parts), "About.")
    assert parts.check(cells, found, live) == []


def problems(parts, cells):
    done, found, live = parts.assemble(cells, "About.")
    return " ".join(parts.check(done, found, live))


def test_the_checks_name_what_is_wrong(parts):
    md, code = parts.md, parts.code
    assert "expected (30, 40)" in problems(parts, small(parts, minutes=(3, 4)))
    unknown = small(parts)
    unknown[8] = md(unknown[8]["source"].replace("[[setup]]", "[[nowhere]]"))
    assert "[[nowhere]] names no section" in problems(parts, unknown)
    bare = small(parts)
    bare[3] = md("# Part 1 · First\n<!-- part: What the first part covers -->\n\nText.")
    assert "code before the first section" in problems(parts, bare)
    silent = small(parts)
    silent[8] = md(silent[8]["source"].replace("<!-- part: What the second part covers -->\n", ""))
    assert "Part 2 has no summary" in problems(parts, silent)
    open_part = small(parts)[:-1]
    assert "Part 2 has no takeaways" in problems(parts, open_part)
    long_cell = small(parts)
    long_cell[4] = code("\n".join(f"x{n} = {n}" for n in range(parts.MAX_CODE_LINES + 1)))
    assert f"{parts.MAX_CODE_LINES + 1} lines" in problems(parts, long_cell)


def test_a_shared_cell_is_starred_only_where_a_notebook_asks(parts):
    cell = [parts.md("## Shared\n<<live:shared>>\n\nText.")]
    chosen = parts.shared(cell, {"shared": "2 | What to show | This section"})
    assert chosen[0]["source"] == "## Shared\n<!-- live: 2 | What to show | This section -->\n\nText."
    assert parts.shared(cell, {})[0]["source"] == "## Shared\n\nText."
    assert cell[0]["source"].startswith("## Shared\n<<live:shared>>"), "the original is not changed"


def test_outputs_are_kept_only_when_no_code_changed(parts, tmp_path, monkeypatch):
    import nbformat

    monkeypatch.delenv("MMDC", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))          # no Mermaid tool: diagrams are left alone
    target = tmp_path / "small.ipynb"
    parts.build(target, small(parts), "Small", "About.")
    notebook = nbformat.read(target, as_version=4)
    for count, cell in enumerate((c for c in notebook.cells if c.cell_type == "code"), 1):
        cell.execution_count = count
        cell.outputs = [nbformat.v4.new_output("stream", name="stdout", text="seen\n")]
    nbformat.write(notebook, target)

    prose = small(parts)
    prose[0] = parts.md("# A title\n\nA better sentence.")
    parts.build(target, prose, "Small", "About.")
    kept = [c for c in nbformat.read(target, as_version=4).cells if c.cell_type == "code"]
    assert [cell.execution_count for cell in kept] == [1, 2, 3]

    changed = small(parts)
    changed[4] = parts.code("x = 2")
    parts.build(target, changed, "Small", "About.")
    fresh = [c for c in nbformat.read(target, as_version=4).cells if c.cell_type == "code"]
    assert [cell.execution_count for cell in fresh] == [None, None, None]
    assert not any(cell.outputs for cell in fresh)
