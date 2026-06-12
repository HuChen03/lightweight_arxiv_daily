import random
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from text_utils import normalize_text


OPENALEX_WORKS_API = "https://api.openalex.org/works"


def build_openalex_query(query_terms: list[str]) -> str:
    cleaned = [normalize_text(term) for term in query_terms if normalize_text(term)]
    return " ".join(cleaned[:5])


def build_openalex_query_candidates(query_terms: list[str]) -> list[str]:
    cleaned = [normalize_text(term) for term in query_terms if normalize_text(term)]
    candidates = [
        " ".join(cleaned[:5]),
        " ".join(cleaned[:3]),
        cleaned[0] if cleaned else "",
    ]
    deduped = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def find_matched_terms(title: str, query_terms: list[str]) -> list[str]:
    lower_title = title.lower()
    matches = []
    for term in query_terms:
        normalized = normalize_text(term)
        if normalized and normalized.lower() in lower_title:
            matches.append(normalized)
    return matches


def get_primary_location(work: dict[str, Any]) -> dict[str, Any]:
    return work.get("primary_location") or work.get("best_oa_location") or {}


def get_work_link(work: dict[str, Any]) -> str:
    location = get_primary_location(work)
    if location.get("landing_page_url"):
        return location["landing_page_url"]
    if work.get("doi"):
        return work["doi"]
    return work.get("id") or ""


def get_work_pdf_link(work: dict[str, Any]) -> str | None:
    location = get_primary_location(work)
    if location.get("pdf_url"):
        return location["pdf_url"]
    best_oa = work.get("best_oa_location") or {}
    return best_oa.get("pdf_url")


def openalex_work_to_result(work: dict[str, Any], query_terms: list[str]) -> dict[str, Any]:
    title = normalize_text(work.get("display_name") or "")
    authors = []
    for authorship in work.get("authorships", []) or []:
        author = authorship.get("author") or {}
        author_name = normalize_text(author.get("display_name") or "")
        if author_name:
            authors.append(author_name)

    return {
        "id": work.get("id") or title,
        "title": title,
        "authors": authors,
        "link": get_work_link(work),
        "pdf_link": get_work_pdf_link(work),
        "published": work.get("publication_date") or str(work.get("publication_year") or ""),
        "summary": "",
        "citation_count": int(work.get("cited_by_count") or 0),
        "matched_keywords": find_matched_terms(title, query_terms) or query_terms[:1],
        "source": "OpenAlex",
        "openalex_id": work.get("id"),
    }


def fetch_openalex_works(query: str, since_date: str, limit: int) -> list[dict[str, Any]]:
    params = {
        "search": query,
        "filter": f"from_publication_date:{since_date}",
        "sort": "cited_by_count:desc",
        "per-page": min(max(limit, 1), 200),
    }
    last_error = None
    for attempt in range(1, 4):
        try:
            response = requests.get(OPENALEX_WORKS_API, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            return payload.get("results", []) or []
        except requests.RequestException as exc:
            last_error = exc
            if attempt == 3:
                raise
            wait_seconds = 2 * attempt + random.uniform(0, 1)
            print(
                f"[warning] OpenAlex request attempt {attempt}/3 failed: {exc}; "
                f"retrying in {wait_seconds:.1f}s",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)
    raise RuntimeError(f"OpenAlex request failed: {last_error}")


def search_high_citation_openalex_papers(
    query_terms: list[str],
    source_titles: set[str] | None = None,
    max_results: int = 5,
    search_limit: int = 20,
) -> list[dict[str, Any]]:
    query_candidates = build_openalex_query_candidates(query_terms)
    if not query_candidates or max_results <= 0:
        return []

    since_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
    works = []
    for query in query_candidates:
        works.extend(fetch_openalex_works(query, since_date=since_date, limit=max(search_limit, max_results)))
        if len(works) >= max_results:
            break
    source_titles = source_titles or set()

    deduped: dict[str, dict[str, Any]] = {}
    for work in works:
        title = normalize_text(work.get("display_name") or "")
        if not title:
            continue
        if title.lower() in source_titles:
            continue
        result = openalex_work_to_result(work, query_terms)
        key = result.get("openalex_id") or title.lower()
        deduped[key] = result

    return sorted(
        deduped.values(),
        key=lambda item: (item.get("citation_count", 0), item.get("published", "")),
        reverse=True,
    )[:max_results]
