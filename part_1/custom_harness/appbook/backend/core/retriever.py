"""Four genuine retrieval paths over one institutional corpus.

The chapter is a retrieval experiment, not four cosmetic renderings of the same
answer. Every method ranks the source corpus independently, then Claude receives
only that method's retrieved passages and generates a directly cited answer.
"""
from __future__ import annotations

import asyncio
import math
import re
from collections import Counter
from functools import lru_cache
from time import perf_counter
from typing import Any

from backend.config import SHARED_DIR, settings


DEMONSTRATION_QUERY = "What should Alex do about the Berlin thermal jacket shortage?"
METHODS = ("keyword", "vector", "hybrid", "rerank")
STOP_WORDS = {
    "a", "about", "an", "and", "are", "as", "at", "be", "been", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has", "have",
    "how", "i", "if", "in", "into", "is", "it", "its", "may", "more", "most",
    "not", "of", "on", "or", "our", "should", "so", "than", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "to", "under",
    "use", "was", "we", "were", "what", "when", "where", "which", "while",
    "who", "why", "will", "with", "would", "you", "your",
}
ACTION_TERMS = {
    "action", "approve", "buy", "decision", "do", "handled", "order", "reorder",
    "recommend", "respond", "restock", "should",
}
SOURCE_AUTHORITY = {
    "restock-playbook.md": 1.00,
    "markdown-policy.md": 1.00,
    "returns-policy.md": 1.00,
    "size-curve-guidance.md": 0.92,
    "supplier-directory.md": 0.88,
    "seasonal-calendar.md": 0.84,
    "glossary.md": 0.80,
    "regional-merch-notes.md": 0.68,
    "review-notes-w40-prep.md": 0.48,
    "review-notes-w39.md": 0.46,
    "review-notes-w38.md": 0.44,
    "review-notes-w37.md": 0.42,
}
CONCEPT_ALIASES = {
    "thermal": {"thermacore", "outerwear", "insulated"},
    "jacket": {"thermacore", "outerwear"},
    "shortage": {"scarce", "reorder", "restock", "below", "low"},
    "buy": {"order", "purchase", "reorder", "restock", "po"},
    "handled": {"actioned", "covered", "open", "po"},
}


def _terms(text: str, *, remove_stop_words: bool = True) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", text.casefold())
    return [token for token in tokens if not remove_stop_words or token not in STOP_WORDS]


@lru_cache(maxsize=1)
def _corpus() -> tuple[dict[str, Any], ...]:
    documents = []
    root = SHARED_DIR / "fixtures" / "notion_pages"
    for path in sorted(root.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ")
        body = "\n".join(line for line in text.splitlines()[1:] if line.strip())
        documents.append({
            "id": path.stem,
            "title": title,
            "page": path.name,
            "text": body,
            "excerpt": " ".join(body.split())[:520],
        })
    return tuple(documents)


def _normalise(rows: list[dict[str, Any]], key: str) -> None:
    values = [float(row[key]) for row in rows]
    low, high = min(values, default=0.0), max(values, default=0.0)
    for row in rows:
        row[f"{key}_normalised"] = 1.0 if high == low and high else (
            (float(row[key]) - low) / (high - low) if high != low else 0.0
        )


def _bm25_rank(query: str) -> list[dict[str, Any]]:
    """Okapi BM25 over the full institutional Markdown corpus."""
    documents = [dict(document) for document in _corpus()]
    query_terms = _terms(query)
    tokenised = [_terms(document["title"] + " " + document["text"]) for document in documents]
    document_frequency: Counter[str] = Counter()
    for tokens in tokenised:
        document_frequency.update(set(tokens))
    average_length = sum(map(len, tokenised)) / max(1, len(tokenised))
    total_documents, k1, b = len(documents), 1.5, 0.75
    for document, tokens in zip(documents, tokenised):
        frequencies = Counter(tokens)
        score = 0.0
        for term in query_terms:
            if not frequencies[term]:
                continue
            inverse_frequency = math.log(
                1 + (total_documents - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            denominator = frequencies[term] + k1 * (
                1 - b + b * len(tokens) / max(1, average_length)
            )
            score += inverse_frequency * frequencies[term] * (k1 + 1) / denominator
        title_hits = len(set(query_terms) & set(_terms(document["title"])))
        document["keyword"] = score + 0.35 * title_hits
        document["provider"] = "Okapi BM25"
    ranked = sorted(documents, key=lambda item: (-item["keyword"], item["page"]))
    _normalise(ranked, "keyword")
    return ranked


def _local_semantic_rank(query: str) -> list[dict[str, Any]]:
    """Deterministic semantic proxy used only by the zero-credential mirror.

    The live path below is the real OracleVS/in-database embedding implementation.
    Alias expansion gives the local teaching mirror semantic behaviour without
    pretending it used Oracle.
    """
    query_tokens = _terms(query)
    expanded = list(query_tokens)
    for token in query_tokens:
        expanded.extend(CONCEPT_ALIASES.get(token, ()))
    documents = [dict(document) for document in _corpus()]
    all_tokens = [expanded] + [_terms(item["title"] + " " + item["text"]) for item in documents]
    document_frequency: Counter[str] = Counter()
    for tokens in all_tokens:
        document_frequency.update(set(tokens))
    total = len(all_tokens)

    def tfidf(tokens: list[str]) -> dict[str, float]:
        frequencies = Counter(tokens)
        return {
            term: frequency * (math.log((1 + total) / (1 + document_frequency[term])) + 1)
            for term, frequency in frequencies.items()
        }

    query_vector = tfidf(expanded)
    for document, tokens in zip(documents, all_tokens[1:]):
        vector = tfidf(tokens)
        dot = sum(query_vector.get(term, 0) * vector.get(term, 0) for term in query_vector)
        denominator = math.sqrt(sum(value * value for value in query_vector.values())) * math.sqrt(
            sum(value * value for value in vector.values())
        )
        document["vector"] = dot / denominator if denominator else 0.0
        document["provider"] = "TF-IDF + governed aliases (local mirror)"
    return sorted(documents, key=lambda item: (-item["vector"], item["page"]))


def _vector_rank(query: str) -> list[dict[str, Any]]:
    if not settings.live:
        return _local_semantic_rank(query)

    from backend.core.oracle_live import get_oracle_stack

    corpus_by_page = {item["page"]: item for item in _corpus()}
    hits = get_oracle_stack().vector_store.similarity_search_with_score(
        query, k=len(corpus_by_page)
    )
    rows = []
    for document, raw_distance in hits:
        page = document.metadata.get("page")
        source = dict(corpus_by_page.get(page, {}))
        if not source:
            source = {
                "id": str(page or document.metadata.get("title", "oracle-document")),
                "title": document.metadata.get("title", "Oracle document"),
                "page": page or "ERPA_DOCS",
                "text": document.page_content,
                "excerpt": " ".join(document.page_content.split())[:520],
            }
        distance = float(raw_distance)
        source.update({
            "vector": max(0.0, 1.0 - distance),
            "vector_distance": distance,
            "provider": "langchain_oracledb.OracleVS / COSINE",
        })
        rows.append(source)
    return rows


def _hybrid_rank(
    keyword_rows: list[dict[str, Any]], vector_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Weighted reciprocal-rank fusion; it uses ranks, not incomparable scores."""
    keyword_position = {item["page"]: rank for rank, item in enumerate(keyword_rows, 1)}
    vector_position = {item["page"]: rank for rank, item in enumerate(vector_rows, 1)}
    source = {item["page"]: dict(item) for item in keyword_rows}
    source.update({item["page"]: {**source.get(item["page"], {}), **item} for item in vector_rows})
    rows = []
    for page, document in source.items():
        keyword_rank = keyword_position.get(page, len(source) + 1)
        vector_rank = vector_position.get(page, len(source) + 1)
        score = 0.45 / (60 + keyword_rank) + 0.55 / (60 + vector_rank)
        rows.append({
            **document,
            "hybrid": score,
            "keyword_rank": keyword_rank,
            "vector_rank": vector_rank,
            "provider": "weighted reciprocal-rank fusion",
        })
    ranked = sorted(rows, key=lambda item: (-item["hybrid"], item["page"]))
    _normalise(ranked, "hybrid")
    return ranked


def _passages(document: dict[str, Any]) -> list[str]:
    parts = re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[A-Z`])", document["text"])
    return [" ".join(part.replace("**", "").split()) for part in parts if len(part.split()) >= 6]


def _expanded_terms(query: str) -> set[str]:
    result = set(_terms(query))
    for token in list(result):
        result.update(CONCEPT_ALIASES.get(token, ()))
    return result


def _passage_relevance(query: str, document: dict[str, Any]) -> float:
    wanted = _expanded_terms(query)
    best = 0.0
    for passage in _passages(document):
        tokens = set(_terms(passage))
        coverage = len(wanted & tokens) / max(1, len(wanted))
        exact_identifiers = sum(
            1 for token in re.findall(r"[A-Z][A-Z0-9-]{2,}", query)
            if token.casefold() in passage.casefold()
        )
        best = max(best, coverage + 0.15 * exact_identifiers)
    return best


def _rerank(query: str, hybrid_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rerank the fused shortlist by passage coverage and source authority.

    For action/decision questions, approved policies and playbooks outrank weekly
    observations.  This is an explicit business retrieval policy, not a scripted
    response for the demonstration query.
    """
    action_intent = bool(set(_terms(query, remove_stop_words=False)) & ACTION_TERMS)
    candidates = [dict(item) for item in hybrid_rows[:8]]
    for item in candidates:
        authority = SOURCE_AUTHORITY.get(item["page"], 0.4)
        passage_score = _passage_relevance(query, item)
        if action_intent:
            score = 0.30 * item["hybrid_normalised"] + 0.48 * authority + 0.22 * passage_score
        else:
            score = 0.58 * item["hybrid_normalised"] + 0.12 * authority + 0.30 * passage_score
        item.update({
            "rerank": score,
            "authority_score": authority,
            "passage_score": passage_score,
            "provider": "query-aware authority + passage reranker",
        })
    return sorted(candidates, key=lambda item: (-item["rerank"], item["page"]))


def compare(query: str) -> dict[str, list[dict[str, Any]]]:
    """Run four real ranking strategies over the same current corpus."""
    keyword = _bm25_rank(query)
    vector = _vector_rank(query)
    hybrid = _hybrid_rank(keyword, vector)
    rerank = _rerank(query, hybrid)
    return {
        "keyword": keyword[:5],
        "vector": vector[:5],
        "hybrid": hybrid[:5],
        "rerank": rerank[:5],
    }


def _best_passage(query: str, document: dict[str, Any], *, semantic: bool) -> str:
    wanted = _expanded_terms(query) if semantic else set(_terms(query))
    # A planner name is useful for document retrieval but should not make a short,
    # unrelated ownership sentence beat a passage containing the actual location,
    # product or decision terms.
    content_terms = wanted - {"alex", "planner", "user"}
    passages = _passages(document)
    if not passages:
        return document["excerpt"]

    def score(passage: str) -> tuple[float, int]:
        tokens = set(_terms(passage))
        content_coverage = len(content_terms & tokens) / max(1, len(content_terms))
        total_coverage = len(wanted & tokens) / max(1, len(wanted))
        return 0.8 * content_coverage + 0.2 * total_coverage, -len(passage)

    return max(passages, key=score)[:520]


CLAUDE_SYSTEM_PROMPT = """You are ERPA, Kata's merchandising copilot.
Answer the user's question directly from the supplied retrieved sources.

Rules:
- The first sentence must give the answer or recommended action, not describe the documents.
- Use only facts in the supplied sources. Never fill gaps from general knowledge.
- Cite every factual claim inline with the supplied source IDs, for example [S1].
- When evidence says an action is already handled, say so and state the condition for escalation.
- If the sources are insufficient or conflict, say exactly what is missing or conflicting.
- Keep the answer concise: one direct opening, then at most three short bullets when useful.
- Do not discuss how the retrieval algorithm works; the interface explains that separately.
- Return Markdown only.
"""


def _claude_prompt(query: str, method: str, context: list[dict[str, Any]]) -> str:
    sources = "\n\n".join(
        f'<source id="S{item["rank"]}" file="{item["source"]}" '
        f'title="{item["title"]}">\n{item["content"]}\n</source>'
        for item in context
    )
    return (
        f"<question>{query}</question>\n"
        f"<retrieval_strategy>{method}</retrieval_strategy>\n"
        f"<retrieved_sources>\n{sources}\n</retrieved_sources>"
    )


async def _answer_with_claude(
    query: str, method: str, context: list[dict[str, Any]], client: Any,
) -> tuple[str, dict[str, Any]]:
    """Synthesize one answer without exposing any other method's context."""
    started = perf_counter()
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1200,
        thinking={"type": settings.anthropic_thinking},
        system=CLAUDE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _claude_prompt(query, method, context)}],
    )
    answer = "\n".join(
        block.text for block in response.content
        if getattr(block, "type", None) == "text" and getattr(block, "text", "").strip()
    ).strip()
    if not answer:
        raise RuntimeError(f"Claude returned no text for the {method} retrieval path")
    usage = getattr(response, "usage", None)
    return answer, {
        "provider": "Anthropic",
        "model": getattr(response, "model", settings.anthropic_model),
        "thinking": settings.anthropic_thinking,
        "latency_ms": round((perf_counter() - started) * 1000, 1),
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "grounding": "Only this retrieval strategy's five passages were supplied to Claude",
    }


async def compare_responses(query: str, thread_id: str = "retrieval-lab") -> dict[str, Any]:
    """Expose four Claude answers and the exact strategy-specific context."""
    del thread_id  # the controlled comparison intentionally has no conversation-state input
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "Part 04 requires ANTHROPIC_API_KEY because every retrieval result is synthesized by Claude."
        )
    rankings = compare(query)
    labels = {
        "keyword": (
            "Keyword / BM25",
            "Real Okapi BM25 over the complete institutional Markdown corpus.",
        ),
        "vector": (
            "Oracle vector" if settings.live else "Semantic vector mirror",
            "OracleVS cosine retrieval using Oracle in-database embeddings."
            if settings.live else "TF-IDF with governed aliases; the zero-credential mirror is explicitly not Oracle.",
        ),
        "hybrid": (
            "Hybrid fusion",
            "Weighted reciprocal-rank fusion of the independently produced BM25 and vector lists.",
        ),
        "rerank": (
            "Authority reranker",
            "The fused shortlist is rescored by answer-bearing passage coverage and governed source authority.",
        ),
    }
    methods = {}
    score_key = {"keyword": "keyword", "vector": "vector", "hybrid": "hybrid", "rerank": "rerank"}
    for method, (label, explanation) in labels.items():
        documents = rankings[method]
        context = [
            {
                "rank": index + 1,
                "kind": "institutional document",
                "title": item["title"],
                "source": item["page"],
                "provider": item["provider"],
                "score": float(item.get(score_key[method], 0.0)),
                "score_kind": "relevance (higher is better)",
                "content": _best_passage(query, item, semantic=method != "keyword"),
            }
            for index, item in enumerate(documents)
        ]
        methods[method] = {
            "label": label,
            "explanation": explanation,
            "top_source": documents[0]["page"],
            "ranking": [item["page"] for item in documents],
            "sources": [{
                "rank": item["rank"], "title": item["title"], "source": item["source"],
                "provider": item["provider"], "score": item["score"],
            } for item in context],
            "context": context,
            "context_window": {
                "items": len(context),
                "estimated_tokens": sum(max(1, len(item["content"].split())) for item in context),
                "retrieval_method": method,
                "corpus_documents": len(_corpus()),
            },
        }
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    generated = await asyncio.gather(*(
        _answer_with_claude(query, method, methods[method]["context"], client)
        for method in METHODS
    ))
    for method, (answer, generation) in zip(METHODS, generated):
        methods[method]["answer"] = answer
        methods[method]["generation"] = generation
    signatures = {method: tuple(payload["ranking"]) for method, payload in methods.items()}
    return {
        "query": query,
        "methods": methods,
        "experiment": {
            "real_query": True,
            "corpus": "institutional Markdown pages seeded into OracleVS",
            "corpus_documents": len(_corpus()),
            "rankings_differ": len(set(signatures.values())) > 1,
            "unique_top_sources": len({payload["top_source"] for payload in methods.values()}),
            "top_sources": {method: payload["top_source"] for method, payload in methods.items()},
            "answer_policy": "Claude synthesis: each answer can use only its strategy's five retrieved passages",
            "answer_model": settings.anthropic_model,
            "thinking": settings.anthropic_thinking,
        },
    }
