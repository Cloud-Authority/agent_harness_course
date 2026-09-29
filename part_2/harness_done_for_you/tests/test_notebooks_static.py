"""Static checks on the two notebooks: form, independence, honesty of the saved run.

A notebook has to stand alone, read as a lesson and leak nothing. These checks
read the saved ``.ipynb`` files. They run no cell and need no network.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

TRACK = Path(__file__).resolve().parents[1]
MAX_CODE_LINES = 22
LOCAL_IMPORT = re.compile(
    r"^\s*(from|import)\s+(ppa_dfy|bootstrap|policy|world|practice|notebook_parts|scripts)\b", re.M)
LOCAL_PATH = re.compile(r"_shared|practice_slice|sys\.path|ppa_dfy")
PART = re.compile(r"^# Part (\d+) · (.+)$", re.M)
SECTION = re.compile(r"^## (\d+)\.(\d+) · (\u2b50 )?(.+)$", re.M)
STAR = "\u2b50"
GUIDE = ("## How to use this notebook", "## Contents", "## The live path")


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TRACK / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def source(cell) -> str:
    return "".join(cell["source"])


def code_cells(notebook):
    return [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]


def executed(notebook) -> bool:
    return any(cell.get("execution_count") for cell in code_cells(notebook))


def output_text(cell) -> str:
    parts = []
    for output in cell.get("outputs", []):
        parts.append("".join(output.get("text", [])))
        data = output.get("data", {})
        parts += ["".join(data.get(kind, [])) for kind in ("text/plain", "text/markdown")]
    return "\n".join(parts)


# ── Form ─────────────────────────────────────────────────────────────────────

def test_the_kernel_is_the_portable_python3(notebook):
    spec = notebook["metadata"]["kernelspec"]
    assert spec["name"] == "python3" and spec["language"] == "python"
    assert not re.search(r"/|\\|venv|conda", spec["display_name"], re.I)


def test_a_markdown_cell_comes_before_every_code_cell(notebook):
    cells = notebook["cells"]
    assert cells[0]["cell_type"] == "markdown" and source(cells[0]).startswith("# ")
    for index, cell in enumerate(cells):
        if cell["cell_type"] == "code":
            assert cells[index - 1]["cell_type"] == "markdown", f"cell {index} has no text before it"


def test_code_cells_are_short(notebook):
    lengths = [len(source(cell).splitlines()) for cell in code_cells(notebook)]
    assert max(lengths) <= MAX_CODE_LINES
    assert sum(lengths) / len(lengths) <= 15, "the average cell has grown too long"


def test_parts_are_numbered_and_each_closes_with_takeaways(notebook):
    parts = load("notebook_parts")
    cells = [{"kind": cell["cell_type"], "source": source(cell)} for cell in notebook["cells"]]
    assert parts.check_parts(cells) == []
    assert len(PART.findall("\n".join(cell["source"] for cell in cells))) >= 10
    left = [cell["source"][:80] for cell in cells if cell["kind"] == "markdown"
            and re.search(r"<!--|<<live:|\[\[[a-z0-9-]+\]\]", cell["source"])]
    assert not left, "a builder marker was left in the notebook"


def test_diagrams_are_embedded_as_images(notebook):
    """Every viewer shows an image. Only some viewers draw a Mermaid block."""
    cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "markdown"]
    assert not [cell for cell in cells if "```mermaid" in source(cell)]
    shown = [name for cell in cells for name in re.findall(r"\(attachment:([^)]+)\)", source(cell))]
    held = {name: data for cell in cells for name, data in cell.get("attachments", {}).items()}
    assert len(shown) >= 6 and sorted(shown) == sorted(held)
    folder = notebook["path"].parent / "diagrams"
    for name, data in held.items():
        assert len(data["image/png"]) > 1000
        assert (folder / name).is_file() and (folder / name).with_suffix(".mmd").is_file()


def test_the_only_emoji_is_the_star_of_a_live_section(notebook):
    other = re.compile("[\U0001F300-\U0001FAFF☀-⭏⭑-⯿]")
    for index, cell in enumerate(notebook["cells"]):
        text = source(cell)
        assert not other.search(text), f"cell {index} holds an emoji"
        if STAR in text and not text.startswith(GUIDE):
            starred = [line for line in text.splitlines() if STAR in line]
            assert all(SECTION.match(line) for line in starred), f"cell {index}: {starred}"


# ── The outline ──────────────────────────────────────────────────────────────

def headings(notebook, level):
    found = []
    for cell in notebook["cells"]:
        if cell["cell_type"] == "markdown":
            found += [line for line in source(cell).splitlines() if line.startswith(level + " ")]
    return found


def test_sections_are_numbered_inside_their_part(notebook):
    part, expected = 0, 0
    for cell in notebook["cells"]:
        for line in source(cell).splitlines() if cell["cell_type"] == "markdown" else []:
            if PART.match(line):
                part, expected = int(PART.match(line).group(1)), 0
            elif line.startswith("## ") and part and not line.startswith("## Takeaways"):
                found = SECTION.match(line)
                expected += 1
                assert found, f"{line!r} has no number"
                assert (int(found.group(1)), int(found.group(2))) == (part, expected), line


def test_takeaways_nest_under_their_part(notebook):
    parts = [int(number) for number, _ in PART.findall("\n".join(headings(notebook, "#")))]
    closing = [line for line in headings(notebook, "##") if line.startswith("## Takeaways")]
    assert closing == [f"## Takeaways · Part {number}" for number in parts]
    assert not [line for line in headings(notebook, "###") if "Takeaways" in line]


def test_the_guide_comes_before_the_first_part(notebook):
    text = [source(cell) for cell in notebook["cells"] if cell["cell_type"] == "markdown"]
    first_part = next(index for index, cell in enumerate(text) if PART.search(cell))
    guide = [index for title in GUIDE for index, cell in enumerate(text) if cell.startswith(title)]
    assert len(guide) == 3 and guide == sorted(guide) and guide[-1] < first_part
    use = text[guide[0]]
    assert "No sign-in is needed" in use and "mail or calendar" in use
    assert "\n".join(text).count("No sign-in is needed") == 1


def test_the_contents_list_every_part_with_its_stars(notebook):
    text = [source(cell) for cell in notebook["cells"] if cell["cell_type"] == "markdown"]
    contents = next(cell for cell in text if cell.startswith("## Contents"))
    rows = [[item.strip() for item in line.strip("|").split("|")]
            for line in contents.splitlines() if re.match(r"^\| \d+ \|", line)]
    parts = PART.findall("\n".join(headings(notebook, "#")))
    assert [(row[0], row[1]) for row in rows] == parts
    assert all(len(row[2]) > 20 for row in rows), "every part has a one-line summary"
    stars = {number: 0 for number, _ in parts}
    for found in SECTION.finditer("\n".join(headings(notebook, "##"))):
        stars[found.group(1)] += bool(found.group(3))
    assert [row[3].count(STAR) for row in rows] == [stars[row[0]] for row in rows]


def test_the_live_path_is_the_starred_sections_in_order(notebook):
    text = [source(cell) for cell in notebook["cells"] if cell["cell_type"] == "markdown"]
    path = next(cell for cell in text if cell.startswith("## The live path"))
    rows = [[item.strip() for item in line.strip("|").split("|")]
            for line in path.splitlines() if re.match(r"^\| \d+\.\d+ · ", line)]
    sections = list(SECTION.finditer("\n".join(headings(notebook, "##"))))
    starred = [f"{found.group(1)}.{found.group(2)} · {found.group(4)}"
               for found in sections if found.group(3)]
    assert [row[0] for row in rows] == starred and len(starred) >= 10
    minutes = sum(int(row[2]) for row in rows)
    assert 30 <= minutes <= 40 and f"about {minutes} minutes" in path
    known = {f"{found.group(1)}.{found.group(2)}" for found in sections}
    for row in rows:
        assert len(row[1]) > 20 and row[3], row
        assert set(re.findall(r"\b\d+\.\d+\b", row[3])) <= known, row
        assert "[[" not in row[1] + row[3]


# ── Independence ─────────────────────────────────────────────────────────────

def test_the_first_code_cell_installs_the_packages(notebook):
    first = source(code_cells(notebook)[0])
    assert "%pip install" in first and "memorizz" in first
    for package in ("pandas", "pyarrow", "huggingface_hub"):
        assert package in first


def test_no_cell_imports_course_code(notebook):
    for index, cell in enumerate(code_cells(notebook)):
        text = source(cell)
        assert not LOCAL_IMPORT.search(text), f"code cell {index} imports course code"
        assert not LOCAL_PATH.search(text), f"code cell {index} reaches into the repository"


def test_data_comes_from_hugging_face_at_pinned_revisions(notebook):
    text = "\n".join(source(cell) for cell in code_cells(notebook))
    revisions = dict(re.findall(r'(MAIL_REV|ATTACK_REV) = "([0-9a-f]{40})"', text))
    assert set(revisions) == {"MAIL_REV", "ATTACK_REV"}
    assert "hf://datasets/corbt/enron-emails@{MAIL_REV}" in text
    assert "pd.read_parquet(" in text and "filters=" in text
    assert 'pd.Timestamp(day, tz="UTC")' in text, "dates are compared as moments with a timezone"
    assert re.search(r"hf_hub_download\(\"microsoft/llmail-inject-challenge\"", text)
    assert "revision=ATTACK_REV" in text and 'reason") == "api_triggered"' in text


def test_the_only_engine_for_tables_is_pandas(notebook):
    """No second database engine appears in the course material."""
    other = "duck" + "db"
    for cell in notebook["cells"]:
        assert other not in (source(cell) + output_text(cell)).lower()


def test_keys_are_read_from_the_environment_and_never_shown(notebook):
    text = "\n".join(source(cell) for cell in code_cells(notebook))
    assert "getpass(" in text and "ANTHROPIC_API_KEY" in text
    assert not re.search(r"print\([^)]*os\.environ\[[^\]]*KEY", text)
    assert not re.search(r"(sk-ant-|tvly-)[A-Za-z0-9_-]{6,}", text)


def test_nothing_about_the_world_is_typed_in(notebook, world):
    """Values of the loaded world may appear in outputs, never in what a person wrote."""
    persona = world["persona"]
    values = {persona["email"], persona["timezone"], world["anchor_day"]}
    values |= set(persona["name"].split())
    values |= {mail["thread_id"] for mail in world["emails"]}
    values |= {mail["from_email"] for mail in world["emails"]}
    values |= {event["event_id"] for event in world["events"]}
    values |= {contact["email"] for contact in world["contacts"]}
    scenario = [cell for cell in code_cells(notebook) if source(cell).startswith("MAILBOX = ")]
    assert len(scenario) == 1, "the scenario parameters live in exactly one cell"
    for index, cell in enumerate(notebook["cells"]):
        if cell is scenario[0]:
            continue
        text = source(cell).lower()
        found = sorted(value for value in values if value and value.lower() in text)
        assert not found, f"cell {index} names {found}"


# ── The saved run ────────────────────────────────────────────────────────────

def test_the_saved_run_went_top_to_bottom_without_an_error(notebook):
    if not executed(notebook):
        pytest.skip("the notebook is saved without outputs")
    counts = [cell.get("execution_count") for cell in code_cells(notebook)]
    assert counts == list(range(1, len(counts) + 1))
    for index, cell in enumerate(code_cells(notebook)):
        kinds = [output["output_type"] for output in cell.get("outputs", [])]
        assert "error" not in kinds, f"code cell {index} raised"
        assert "Traceback (most recent call last)" not in output_text(cell)


def test_what_to_watch_is_followed_by_something_to_see(notebook):
    if not executed(notebook):
        pytest.skip("the notebook is saved without outputs")
    cells = notebook["cells"]
    for index, cell in enumerate(cells[:-1]):
        if cell["cell_type"] == "markdown" and re.search(r"^\*\*What to watch", source(cell), re.M):
            following = cells[index + 1]
            assert following["cell_type"] == "code"
            assert output_text(following).strip(), f"cell {index + 1} shows nothing to watch"


def test_outputs_are_not_flooded_with_warnings(notebook):
    for index, cell in enumerate(code_cells(notebook)):
        stderr = "".join("".join(output.get("text", [])) for output in cell.get("outputs", [])
                         if output.get("name") == "stderr")
        assert len(stderr.splitlines()) <= 3, f"code cell {index} prints {len(stderr)} characters of warnings"


def test_the_saved_notebook_leaks_nothing(notebook):
    scan = load("scan_notebooks")
    assert scan.scan(notebook["path"]) == []


def test_a_skipped_harness_has_no_invented_answer(notebook):
    if notebook["name"] != "metaharness" or not executed(notebook):
        pytest.skip("applies to the executed meta-harness notebook")
    text = "\n".join(output_text(cell) for cell in code_cells(notebook))
    if "DEEPSEEK_API_KEY present': False" not in text:
        pytest.skip("the saved run had a DeepSeek key")
    assert "deepseek: skipped (authentication_required)" in text
    assert "deepseek: succeeded" not in text


# ── A measurement that reads prose ───────────────────────────────────────────

def test_a_warning_is_read_from_the_line_or_from_its_heading(notebook):
    """The anchor on flagged attacks reads an answer. It must not depend on its layout."""
    if notebook["name"] != "memagent":
        pytest.skip("the MemAgent notebook reads prose, the other one reads JSON")
    cell = next(cell for cell in code_cells(notebook) if "def flagged(answer, threads)" in source(cell))
    names = {"re": re}
    exec(source(cell).split("report(")[0], names)
    flagged, threads = names["flagged"], {"thr-one", "thr-two"}

    in_the_line = "- [thr-one] and [thr-two] come from unverified senders. I made no task."
    under_a_heading = ("## Suspicious mail, no action taken\n"
                       "- **[thr-one] and [thr-two]:** each asks for an email to an outside address.")
    under_a_bold_line = "**Unknown senders**\n- [thr-one]\n- [thr-two]"
    as_ordinary_work = ("## Tasks created\n| T-1 | [thr-one] | Send the confirmation |\n"
                        "## Replies drafted\n- [thr-two]: a reply is saved")
    half = "## Suspicious\n- [thr-one] asks for mail to be sent\n## Tasks created\n- [thr-two]"
    assert flagged(in_the_line, threads) == threads
    assert flagged(under_a_heading, threads) == threads
    assert flagged(under_a_bold_line, threads) == threads
    assert flagged(as_ordinary_work, threads) == set()
    assert flagged(half, threads) == {"thr-one"}
    assert flagged("", threads) == set()
