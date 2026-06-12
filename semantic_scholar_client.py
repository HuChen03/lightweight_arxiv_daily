import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from text_utils import normalize_text


SEMANTIC_SCHOLAR_SEARCH_API = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_FIELDS = (
    "paperId,title,authors,year,citationCount,url,publicationDate,externalIds,openAccessPdf"
)


def strip_arxiv_version(arxiv_id: str | None) -> str:
    return re.sub(r"v\d+$", "", arxiv_id or "")


def parse_publication_date(publication_date: str | None, year: int | None) -> datetime | None:
    if publication_date:
        try:
            return datetime.strptime(publication_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if year:
        return datetime(year, 1, 1, tzinfo=timezone.utc)
    return None


def is_recent_publication(publication_date: str | None, year: int | None, cutoff: datetime) -> bool:
    if publication_date:
        parsed = parse_publication_date(publication_date, year)
        if parsed:
            return parsed >= cutoff
    if year:
        return year >= cutoff.year
    return False


def build_semantic_query(query_terms: list[str]) -> str:
    cleaned = [normalize_text(term) for term in query_terms if normalize_text(term)]
    return " ".join(cleaned[:5])


def find_matched_terms(title: str, query_terms: list[str]) -> list[str]:
    lower_title = title.lower()
    matches = []
    for term in query_terms:
        normalized = normalize_text(term)
        if normalized and normalized.lower() in lower_title:
            matches.append(normalized)
    return matches


def semantic_paper_to_result(paper: dict[str, Any], query_terms: list[str]) -> dict[str, Any]:
    external_ids = paper.get("externalIds") or {}
    arxiv_id = strip_arxiv_version(external_ids.get("ArXiv"))
    link = paper.get("url")
    if arxiv_id:
        link = f"https://arxiv.org/abs/{arxiv_id}"
    open_access_pdf = paper.get("openAccessPdf") or {}
    authors = [
        normalize_text(author.get("name", ""))
        for author in paper.get("authors", []) or []
        if normalize_text(author.get("name", ""))
    ]
    publication = paper.get("publicationDate") or str(paper.get("year") or "")
    title = normalize_text(paper.get("title") or "")
    return {
        "id": paper.get("paperId") or arxiv_id or title,
        "title": title,
        "authors": authors,
        "link": link,
        "pdf_link": open_access_pdf.get("url"),
        "published": publication,
        "summary": "",
        "citation_count": int(paper.get("citationCount") or 0),
        "matched_keywords": find_matched_terms(title, query_terms) or query_terms[:1],
        "source": "Semantic Scholar",
        "semantic_scholar_id": paper.get("paperId"),
        "arxiv_id": arxiv_id,
    }


def fetch_semantic_scholar_search(query: str, limit: int) -> list[dict[str, Any]]:
    params = {
        "query": query,
        "limit": limit,
        "fields": SEMANTIC_SCHOLAR_FIELDS,
    }
    last_error = None
    for attempt in range(1, 4):
        try:
            response = requests.get(SEMANTIC_SCHOLAR_SEARCH_API, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            return payload.get("data", []) or []
        except requests.RequestException as exc:
            last_error = exc
            if attempt == 3:
                raise
            wait_seconds = 2 * attempt + random.uniform(0, 1)
            print(
                f"[warning] Semantic Scholar request attempt {attempt}/3 failed: {exc}; "
                f"retrying in {wait_seconds:.1f}s",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)
    raise RuntimeError(f"Semantic Scholar request failed: {last_error}")


def search_high_citation_related_papers(
    query_terms: list[str],
    source_ids: set[str],
    max_results: int = 5,
    search_limit: int = 20,
) -> list[dict[str, Any]]:
    query = build_semantic_query(query_terms)
    if not query or max_results <= 0:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=365)
    candidates = fetch_semantic_scholar_search(query, limit=max(search_limit, max_results))
    deduped: dict[str, dict[str, Any]] = {}
    source_ids = {strip_arxiv_version(source_id) for source_id in source_ids}

    for paper in candidates:
        if not paper.get("title"):
            continue
        external_ids = paper.get("externalIds") or {}
        arxiv_id = strip_arxiv_version(external_ids.get("ArXiv"))
        if arxiv_id and arxiv_id in source_ids:
            continue
        if not is_recent_publication(paper.get("publicationDate"), paper.get("year"), cutoff):
            continue
        result = semantic_paper_to_result(paper, query_terms)
        key = result.get("semantic_scholar_id") or result.get("arxiv_id") or result["title"].lower()
        deduped[key] = result

    return sorted(
        deduped.values(),
        key=lambda item: (item.get("citation_count", 0), item.get("published", "")),
        reverse=True,
    )[:max_results]
