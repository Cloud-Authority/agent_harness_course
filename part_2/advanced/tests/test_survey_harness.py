"""The survey harness's rules, without a model, a search service or a database."""
from __future__ import annotations

from pathlib import Path

ADVANCED = Path(__file__).resolve().parents[1]


def load(module: str):
    from conftest import load_harness
    return load_harness("deep_research", module)


def test_one_work_has_one_key_whatever_the_link():
    evidence = load("harness.evidence")
    assert evidence.canonical("https://arxiv.org/abs/2407.01489") == evidence.canonical("https://arxiv.org/html/2407.01489v2")
    assert evidence.canonical("https://openreview.net/forum?id=a") != evidence.canonical("https://openreview.net/forum?id=b")


def test_titles_lose_the_site_name():
    evidence = load("harness.evidence")
    assert evidence.clean_title("[PDF] A Survey | Semantic Scholar") == "A Survey"
    assert evidence.clean_title("   ") == "Untitled"


def test_the_harness_rules_name_thin_sections(monkeypatch):
    writing = load("harness.writing")
    monkeypatch.setattr(writing, "drafts", lambda paper_id: [
        {"section_key": "intro", "words": 900, "citations": 1},
        {"section_key": "loop", "words": 120, "citations": 1}])
    outline = [{"key": "intro", "kind": "introduction"}, {"key": "loop", "kind": "thematic"}, {"key": "gone", "kind": "thematic"}]
    problems = writing.check_drafts("P", outline)
    assert {p["key"] for p in problems} == {"loop", "gone"}
    assert any("words" in p["problem"] for p in problems) and any("citations" in p["problem"] for p in problems)


def test_markdown_becomes_a_printable_page():
    writing = load("harness.writing")
    html = writing.to_html("# Title\n\nA claim [1].\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- one\n- two\n", "Title")
    assert "<h1>Title</h1>" in html and "<table>" in html and "<li>one</li>" in html and "<title>Title</title>" in html


def test_the_review_sends_the_run_back_only_with_rounds_left():
    graph = load("harness.graph")
    state = {"status": "reviewed_revise", "round": 1, "paper_id": "P", "subject": "s",
             "outline": [{"key": "loop", "kind": "thematic"}],
             "review": {"sections": [{"key": "loop", "needs_more_evidence": True, "queries": ["q1", "q2", "q3"]}]}}
    sends = graph.after_review(state)
    assert isinstance(sends, list) and len(sends) == 1 and sends[0].arg["queries"] == ["q1", "q2"]
    assert graph.after_review({**state, "round": graph.CFG.max_rounds}) == "assemble"
    assert graph.after_review({**state, "status": "reviewed_accept"}) == "assemble"


def test_the_graph_has_the_shape_the_lesson_describes():
    graph = load("harness.graph")
    drawn = graph.build_graph().get_graph()
    names = {n for n in drawn.nodes if not n.startswith("__")}
    assert names == {"scope", "outline_review", "rescope", "gather", "read", "organise", "write", "review", "assemble",
                     "publication_review", "publish", "close"}
