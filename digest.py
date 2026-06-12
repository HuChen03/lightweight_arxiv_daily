import sys
import time
from datetime import datetime, timezone
from typing import Any

from arxiv_client import build_keyword_query, fetch_arxiv_query
from llm_analyzer import analyze_paper_with_llm
from openalex_client import search_high_citation_openalex_papers
from pricing import make_empty_usage
from semantic_scholar_client import search_high_citation_related_papers
from text_utils import normalize_text


def matched_query_terms(paper: dict[str, Any], query_terms: list[str]) -> list[str]:
    haystack = f"{paper.get('title', '')} {paper.get('summary', '')}".lower()
    matches = []
    for term in query_terms:
        normalized = normalize_text(term).lower()
        if normalized and normalized in haystack:
            matches.append(term)
    return matches


def search_arxiv_related_papers(
    query_terms: list[str],
    categories: list[str],
    source_ids: set[str],
    max_results: int = 5,
    search_limit: int = 20,
) -> list[dict[str, Any]]:
    if not query_terms or max_results <= 0:
        return []

    search_query = build_keyword_query(query_terms, categories=categories)
    try:
        candidates = fetch_arxiv_query(search_query, max_results=search_limit)
    except Exception as exc:
        print(f"[warning] related paper search failed for {query_terms}: {exc}", file=sys.stderr)
        return []

    deduped = {}
    for paper in candidates:
        if paper["id"] in source_ids:
            continue
        matches = matched_query_terms(paper, query_terms)
        paper["matched_keywords"] = matches or query_terms[:1]
        score = len(matches) * 10
        try:
            published = datetime.strptime(paper["published"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            score += max(0, 365 - (datetime.now(timezone.utc) - published).days) / 365
        except Exception:
            pass
        paper["related_score"] = score
        deduped[paper["id"]] = paper

    return sorted(deduped.values(), key=lambda item: item.get("related_score", 0), reverse=True)[:max_results]


def search_related_papers(
    query_terms: list[str],
    categories: list[str],
    source_ids: set[str],
    source_titles: set[str] | None = None,
    max_results: int = 5,
    search_limit: int = 20,
) -> list[dict[str, Any]]:
    if not query_terms or max_results <= 0:
        return []

    try:
        openalex_results = search_high_citation_openalex_papers(
            query_terms=query_terms,
            source_titles=source_titles,
            max_results=max_results,
            search_limit=search_limit,
        )
        if openalex_results:
            return openalex_results
    except Exception as exc:
        print(f"[warning] OpenAlex related search failed for {query_terms}: {exc}", file=sys.stderr)

    try:
        semantic_results = search_high_citation_related_papers(
            query_terms=query_terms,
            source_ids=source_ids,
            max_results=max_results,
            search_limit=search_limit,
        )
        if semantic_results:
            return semantic_results
    except Exception as exc:
        print(f"[warning] Semantic Scholar related search failed for {query_terms}: {exc}", file=sys.stderr)

    print("[warning] Falling back to arXiv related search without citation ranking.", file=sys.stderr)
    return search_arxiv_related_papers(
        query_terms=query_terms,
        categories=categories,
        source_ids=source_ids,
        max_results=max_results,
        search_limit=search_limit,
    )


def build_research_digest(
    papers: list[dict[str, Any]],
    categories: list[str],
    model: str,
    base_url: str | None,
    api_key: str | None,
    related_per_paper: int,
    related_search_limit: int,
    max_query_terms: int,
    skip_llm: bool,
) -> list[dict[str, Any]]:
    source_ids = {paper["id"] for paper in papers}
    source_titles = {normalize_text(paper.get("title", "")).lower() for paper in papers}
    digest = []
    for index, paper in enumerate(papers, start=1):
        print(f"Analyzing paper {index}/{len(papers)}: {paper['title'][:70]}...")
        analysis = analyze_paper_with_llm(
            paper=paper,
            model=model,
            base_url=base_url,
            api_key=api_key,
            skip_llm=skip_llm,
        )
        query_terms = analysis.get("query_terms", [])[:max_query_terms]
        related_papers = search_related_papers(
            query_terms=query_terms,
            categories=categories,
            source_ids=source_ids,
            source_titles=source_titles,
            max_results=related_per_paper,
            search_limit=related_search_limit,
        )
        digest.append(
            {
                "source_paper": paper,
                "llm_analysis": analysis,
                "related_papers": related_papers,
                "usage": analysis.get("usage", make_empty_usage(model)),
            }
        )
        if index < len(papers):
            time.sleep(3)
    return digest
