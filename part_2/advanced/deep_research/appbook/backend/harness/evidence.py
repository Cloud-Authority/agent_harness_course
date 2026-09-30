"""Finding, reading and storing evidence. The library is searchable by meaning."""
from __future__ import annotations

import json
import re

import oracledb

from shared.oracle import EMBED, execute, rows

from .config import CFG, tavily
from .tables import new_id


def canonical(url: str) -> str:
    """One key per work: an arXiv paper is the same paper whether it is read as abs, html or pdf."""
    found = re.search(r"arxiv\.org/(?:abs|html|pdf)/(\d{4}\.\d{4,5})", url)
    if found:
        return f"arxiv:{found.group(1)}"
    return re.sub(r"#.*$", "", url.rstrip("/")).lower()


def clean_title(title: str) -> str:
    """Titles as a search engine shows them carry the site's name; the reference list should not."""
    title = re.sub(r"^\[(PDF|HTML)\]\s*", "", title.strip())
    title = re.sub(r"\s*[|·–-]\s*(arXiv|Semantic Scholar|Springer Nature Link|OpenReview|ACM Digital Library|IEEE Xplore|Nature|ScienceDirect)\s*$", "", title)
    return title.strip() or "Untitled"


def search_web(query: str, scholarly: bool = True) -> list[dict]:
    """One search. Scholarly searches stay on the venues where papers live."""
    options = {"search_depth": "advanced", "max_results": CFG.results_per_query}
    if scholarly:
        options["include_domains"] = list(CFG.scholarly_domains)
    found = tavily().search(query, **options)
    return [{"url": item.get("url", ""), "title": item.get("title", ""), "snippet": item.get("content", "")[:2000],
             "score": item.get("score"), "published": (item.get("published_date") or "")[:10]}
            for item in found.get("results", []) if item.get("url")]


def read_pages(urls: list[str]) -> dict[str, str]:
    """The full text of each page, as the search service extracts it."""
    if not urls:
        return {}
    found = tavily().extract(urls=urls)
    return {item["url"]: (item.get("raw_content") or "")[:60_000] for item in found.get("results", [])}


def known_urls(paper_id: str) -> set[str]:
    return {canonical(r["url"]) for r in rows("SELECT url FROM survey_sources WHERE paper_id = :p", {"p": paper_id})}


def keep_source(paper_id: str, section_key: str, query: str, result: dict, content: str, round_no: int) -> str | None:
    """One page becomes one row, embedded inside the database as it is stored.

    Sections gather in parallel, so two of them can find the same new page at the
    same moment. The unique constraint on (paper, url) decides: the second insert
    is refused and the page is kept once, under the section that stored it first.
    """
    source_id = new_id("S")
    seed = f"{result['title']}\n{result['snippet']}"[:4000]
    try:
        execute(f"""INSERT INTO survey_sources (source_id, paper_id, section_key, url, title, published, query, score,
                    snippet, content, content_chars, round, embedding)
                    VALUES (:id, :p, :s, :u, :t, :d, :q, :sc, :sn, :c, :n, :r, {EMBED})""",
                {"id": source_id, "p": paper_id, "s": section_key, "u": result["url"][:2000], "t": result["title"][:1000],
                 "d": result.get("published", ""), "q": query[:1000], "sc": result.get("score"), "sn": result["snippet"][:4000],
                 "c": content, "n": len(content), "r": round_no, "text": seed})
    except oracledb.IntegrityError:
        return None
    return source_id


def gather_for_section(paper_id: str, section: dict, queries: list[str], round_no: int = 1) -> list[dict]:
    """Search, drop what the library already holds, read the best pages, store them."""
    seen = known_urls(paper_id)
    candidates: dict[str, dict] = {}
    for query in queries:
        for result in search_web(query):
            key = canonical(result["url"])
            if key not in seen and key not in candidates:
                candidates[key] = {**result, "title": clean_title(result["title"]), "query": query}
    best = sorted(candidates.values(), key=lambda r: -(r["score"] or 0))[:CFG.sources_per_section]
    pages = read_pages([r["url"] for r in best])
    kept = []
    for result in best:
        content = pages.get(result["url"]) or result["snippet"]
        source_id = keep_source(paper_id, section["key"], result["query"], result, content, round_no)
        if source_id:
            kept.append({"source_id": source_id, "section_key": section["key"], "url": result["url"],
                         "title": result["title"], "chars": len(content)})
    return kept


def sources_for(paper_id: str, section_key: str | None = None) -> list[dict]:
    where = "paper_id = :p" + (" AND section_key = :s" if section_key else "")
    binds = {"p": paper_id, **({"s": section_key} if section_key else {})}
    return rows(f"SELECT source_id, section_key, url, title, published, content_chars, round FROM survey_sources "
                f"WHERE {where} ORDER BY fetched_at", binds)


def similar_sources(paper_id: str, text: str, limit: int = 5, exclude_section: str | None = None) -> list[dict]:
    """The library, asked by meaning: the sources closest to a piece of text."""
    where = "paper_id = :p" + (" AND section_key <> :s" if exclude_section else "")
    binds = {"p": paper_id, "text": text[:4000], "k": limit, **({"s": exclude_section} if exclude_section else {})}
    return rows(f"""SELECT source_id, section_key, title, url,
                           ROUND(VECTOR_DISTANCE(embedding, {EMBED}, COSINE), 4) AS distance
                      FROM survey_sources WHERE {where}
                     ORDER BY distance FETCH FIRST :k ROWS ONLY""", binds)


def source_text(source_id: str, limit: int = 14_000) -> dict:
    found = rows("SELECT source_id, title, url, published, content FROM survey_sources WHERE source_id = :s",
                 {"s": source_id})[0]
    text = re.sub(r"\n{3,}", "\n\n", found["content"] or "")
    return {**found, "content": text[:limit]}
