"""The workspace export: complete, deterministic, delimited and read-only.

A coding harness reads the exported folder instead of calling trusted tools, so
the folder has to carry everything the tools would have answered. Each test
states a rule. None asserts a hand-picked thread, person or time.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from ppa_dfy import workspace_export, world as world_module


@pytest.fixture(scope="module")
def exported(world, scratch):
    manifest = workspace_export.export_workspace(world, scratch / "export-a")
    return manifest, Path(manifest["path"])


def read_json(root: Path, relative: str):
    return json.loads((root / relative).read_text(encoding="utf-8"))


def test_every_listed_file_exists_with_its_hash(exported):
    manifest, root = exported
    assert manifest["files"], "the export wrote files"
    for relative, digest in manifest["files"].items():
        text = (root / relative).read_text(encoding="utf-8")
        assert workspace_export.hashlib.sha256(text.encode("utf-8")).hexdigest() == digest


def test_there_is_one_file_per_inbox_thread(exported, world):
    _, root = exported
    threads = {mail["thread_id"] for mail in world["emails"]}
    files = {path.stem for path in (root / "inbox").glob("*.md")} - {"INDEX"}
    assert files == threads


def test_the_same_world_gives_the_same_bytes(exported, world, scratch):
    manifest, _ = exported
    again = workspace_export.export_workspace(world, scratch / "export-b")
    assert again["tree_sha256"] == manifest["tree_sha256"]
    assert again["content_sha256"] == manifest["content_sha256"]
    assert again["git_commit"] == manifest["git_commit"]


def test_empty_collections_are_written_as_empty_lists(exported, world):
    _, root = exported
    assert world["tasks"] == [] and world["focus_log"] == []
    assert read_json(root, "tasks.json") == []
    assert read_json(root, "focus_log.json") == []
    assert read_json(root, "governed/tasks.json")["top_three"] == []
    assert "No pages have been recorded yet." in (root / "pages/INDEX.md").read_text()
    assert "Empty in this snapshot" in (root / "README.md").read_text()


def test_live_state_is_exported_and_changes_the_governed_answers(world, known, scratch):
    thread = next(thread for thread, category in known["triage_categories"].items()
                  if category == "task")
    task = {"task_id": "T-TEST", "title": "A task made by a test", "status": "OPEN",
            "priority": 3, "due_at": None, "est_pomodoros": 1, "carry_over_count": 0,
            "source_ref": thread, "created_at": world["scenario_now"]}
    manifest = workspace_export.export_workspace(world, scratch / "export-c", tasks=[task])
    root = Path(manifest["path"])
    governed = read_json(root, "governed/triage.json")
    row = next(item for item in governed["threads"] if item["thread_id"] == thread)
    assert row["category"] == "tracked" and row["tracked_task_id"] == "T-TEST"
    assert read_json(root, "governed/tasks.json")["tracked_threads"] == {thread: "T-TEST"}


def test_governed_files_repeat_what_the_policy_says(exported, world, known):
    _, root = exported
    governed = read_json(root, "governed/triage.json")
    assert [row["thread_id"] for row in governed["threads"]] == known["triage_order"]
    assert governed["lead_thread_id"] == known["triage_first_thread"]
    today = read_json(root, "governed/calendar.json")["days"][0]
    assert today["day"] == world["anchor_day"]
    assert today["meeting_rule_violations"] == known["meeting_rule_violations"]
    assert today["no_meetings_before"] == world["persona"]["no_meetings_before"]


def test_every_body_is_delimited_as_untrusted(exported, world):
    _, root = exported
    for mail in world["emails"]:
        text = (root / "inbox" / f"{mail['thread_id']}.md").read_text(encoding="utf-8")
        assert text.count("<untrusted_content") == text.count("</untrusted_content>") >= 2
        header = text.split("<untrusted_content", 1)[0]
        first_line = (mail.get("body") or "").strip().splitlines()[:1]
        if first_line and len(first_line[0]) > 25:
            assert first_line[0] not in header, "external text leaked into the governed header"


def test_index_files_name_threads_in_governed_order(exported, known):
    _, root = exported
    index = (root / "inbox" / "INDEX.md").read_text(encoding="utf-8")
    positions = [index.index(f"| {thread} |") for thread in known["triage_order"]]
    assert positions == sorted(positions)


def test_the_export_is_read_only_and_can_be_replaced(world, scratch):
    manifest = workspace_export.export_workspace(world, scratch / "export-d")
    root = Path(manifest["path"])
    files = [path for path in root.rglob("*") if path.is_file() and ".git" not in path.parts]
    assert files and all(not path.stat().st_mode & stat.S_IWUSR for path in files)
    assert not os.access(root / "README.md", os.W_OK)
    again = workspace_export.export_workspace(world, root)
    assert again["tree_sha256"] == manifest["tree_sha256"]


def test_the_readme_is_written_from_the_data(exported, world):
    _, root = exported
    readme = (root / "README.md").read_text(encoding="utf-8")
    persona = world["persona"]
    for value in (persona["email"], persona["timezone"], world["scenario_now"],
                  persona["no_meetings_before"]):
        assert str(value) in readme


def test_the_tree_hash_notices_a_change(world, scratch):
    manifest = workspace_export.export_workspace(world, scratch / "export-e", read_only=False)
    root = Path(manifest["path"])
    (root / "tasks.json").write_text("[1]\n", encoding="utf-8")
    assert workspace_export.tree_hash(root) != manifest["tree_sha256"]
