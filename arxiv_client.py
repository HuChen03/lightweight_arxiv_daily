import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import feedparser
import requests

from config import DEFAULT_CATEGORY
from text_utils import normalize_text
from translation import translate_to_chinese


ARXIV_API = "https://export.arxiv.org/api/query"


def extract_arxiv_id(link: str) -> str:
    path = urlparse(link).path
    arxiv_id = path.rsplit("/", 1)[-1]
    return re.sub(r"v\d+$", "", arxiv_id)


def get_entry_categories(entry: Any) -> list[str]:
    categories = []
    for tag in getattr(entry, "tags", []) or []:
        term = tag.get("term") if isinstance(tag, dict) else getattr(tag, "term", None)
        if term:
            categories.append(term)
    return categories


def get_primary_category(entry: Any) -> str | None:
    primary = getattr(entry, "arxiv_primary_category", None)
    if isinstance(primary, dict):
        return primary.get("term")
    if primary is not None:
        return getattr(primary, "term", None)
    categories = get_entry_categories(entry)
    return categories[0] if categories else None


def get_pdf_link(entry: Any) -> str | None:
    for link in getattr(entry, "links", []) or []:
        link_type = link.get("type") if isinstance(link, dict) else getattr(link, "type", "")
        title = link.get("title") if isinstance(link, dict) else getattr(link, "title", "")
        href = link.get("href") if isinstance(link, dict) else getattr(link, "href", "")
        if link_type == "application/pdf" or title == "pdf":
            return href
    if getattr(entry, "link", None):
        return entry.link.replace("/abs/", "/pdf/")
    return None


def entry_to_paper(entry: Any) -> dict[str, Any]:
    link = entry.link
    return {
        "id": extract_arxiv_id(link),
        "title": normalize_text(entry.title),
        "authors": [a.name for a in getattr(entry, "authors", [])],
        "link": link,
        "pdf_link": get_pdf_link(entry),
        "published": entry.published,
        "updated": getattr(entry, "updated", entry.published),
        "summary": normalize_text(entry.summary),
        "categories": get_entry_categories(entry),
        "primary_category": get_primary_category(entry),
    }


def build_category_query(categories: list[str]) -> str:
    parts = [f"cat:{category}" for category in categories]
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"


def fetch_arxiv_query(search_query: str, max_results: int = 100, start: int = 0) -> list[dict[str, Any]]:
    params = {
        "search_query": search_query,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    last_error = None
    for attempt in range(1, 4):
        try:
            response = requests.get(ARXIV_API, params=params, timeout=30)
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            last_error = exc
            if attempt == 3:
                raise
            wait_seconds = 2 * attempt + random.uniform(0, 1)
            print(
                f"[warning] arXiv request attempt {attempt}/3 failed: {exc}; "
                f"retrying in {wait_seconds:.1f}s",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)
    else:
        raise RuntimeError(f"arXiv request failed: {last_error}")
    feed = feedparser.parse(response.text)
    if getattr(feed, "bozo", False):
        print(f"[warning] arXiv feed parse warning: {getattr(feed, 'bozo_exception', '')}", file=sys.stderr)
    return [entry_to_paper(entry) for entry in feed.entries]


def fetch_recent_papers(
    categories: list[str],
    days: int = 3,
    max_results: int = 10,
    translate: bool = False,
    include_cross_list: bool = False,
) -> list[dict[str, Any]]:
    search_query = build_category_query(categories)
    fetch_limit = max(max_results * 5, 50 if not include_cross_list else max_results)
    all_papers = fetch_arxiv_query(search_query, max_results=fetch_limit)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    category_set = set(categories)

    selected = []
    for paper in all_papers:
        published = datetime.strptime(paper["published"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if not include_cross_list and paper.get("primary_category") not in category_set:
            continue
        if published >= cutoff:
            selected.append((published, paper))

    selected.sort(key=lambda item: item[0], reverse=True)

    papers = [paper for _, paper in selected[:max_results]]

    if translate:
        for paper in papers:
            print(f"Translating paper: {paper['title'][:50]}...")
            paper["translated_title"] = translate_to_chinese(paper["title"])

    return papers


def build_keyword_query(query_terms: list[str], categories: list[str] | None = None) -> str:
    cleaned_terms = []
    for term in query_terms:
        term = normalize_text(term).replace('"', "")
        if term:
            cleaned_terms.append(f'all:"{term}"')
    if not cleaned_terms:
        return build_category_query(categories or [DEFAULT_CATEGORY])

    keyword_query = " OR ".join(cleaned_terms)
    if categories:
        return f"{build_category_query(categories)} AND ({keyword_query})"
    return keyword_query
