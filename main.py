import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import feedparser
import requests
from dotenv import load_dotenv
from translate import Translator as OfflineTranslator

from email_notifier import send_email_notification


ARXIV_API = "https://export.arxiv.org/api/query"
DEFAULT_CATEGORY = "hep-ex"
DEFAULT_USD_CNY_RATE = 7.2

# USD prices per 1M tokens. Override with LLM_INPUT_PRICE_USD_PER_1M and
# LLM_OUTPUT_PRICE_USD_PER_1M when using a non-OpenAI-compatible provider.
MODEL_PRICES_USD_PER_1M = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
    "gpt-5.5": {"input": 5.00, "output": 30.00},
    "gpt-5.4": {"input": 2.50, "output": 15.00},
    "gpt-5.4-mini": {"input": 0.75, "output": 4.50},
    # DeepSeek prices use cache-miss input rates for conservative estimates.
    "deepseek-v4-flash": {"input": 0.14, "output": 0.28},
    "deepseek-v4-pro": {"input": 0.435, "output": 0.87},
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.14, "output": 0.28},
}

load_dotenv(dotenv_path=Path(__file__).parent / ".env")


def _google_split_text(text, max_chars=2000):
    """Split long text into chunks for Google Translate."""
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(sentence), max_chars):
                chunks.append(sentence[i:i + max_chars])
            continue
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current += " " + sentence
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def _google_translate_chunk(text, source="en", target="zh-CN", timeout=25):
    """Translate a single chunk via Google's unofficial Translate API."""
    params = {
        "client": "gtx",
        "sl": source,
        "tl": target,
        "dt": "t",
        "q": text,
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
    }
    try:
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params=params, headers=headers, timeout=timeout,
        )
    except requests.Timeout:
        raise Exception("translate_timeout")
    except requests.RequestException as e:
        raise Exception(f"translate_network_error: {e}")

    if r.status_code in (403, 429):
        raise Exception(f"translate_blocked_or_rate_limited_http_{r.status_code}")
    if 500 <= r.status_code <= 599:
        raise Exception(f"translate_server_error_http_{r.status_code}")
    if r.status_code != 200:
        raise Exception(f"translate_unexpected_http_status_{r.status_code}")

    raw = r.text.strip()
    if not raw:
        raise Exception("translate_empty_response")
    if raw.startswith("<") or "text/html" in r.headers.get("content-type", "").lower():
        raise Exception("translate_html_response_instead_of_json")

    try:
        data = r.json()
    except json.JSONDecodeError as e:
        raise Exception("translate_malformed_json") from e

    if not isinstance(data, list) or not data or not isinstance(data[0], list):
        raise Exception("translate_unexpected_json_structure")
    pieces = []
    for seg in data[0]:
        if isinstance(seg, list) and len(seg) > 0 and isinstance(seg[0], str):
            pieces.append(seg[0])
    translated = "".join(pieces).strip()
    if not translated:
        raise Exception("translate_empty_translation_text")
    return translated


def _google_translate_with_retries(text, source="en", target="zh-CN", retries=3, sleep_base=2.0):
    """Translate text via Google with chunking and retry logic."""
    chunks = _google_split_text(text)
    if not chunks:
        raise Exception("translate_empty_input_text")

    translated_chunks = []
    for idx, chunk in enumerate(chunks, start=1):
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                translated_chunks.append(
                    _google_translate_chunk(chunk, source=source, target=target)
                )
                break
            except Exception as e:
                last_error = e
                wait = sleep_base * attempt + random.uniform(0.0, 1.5)
                print(
                    f"[warning] Google translate chunk {idx}/{len(chunks)} attempt "
                    f"{attempt}/{retries} failed: {e}",
                    file=sys.stderr,
                )
                if attempt < retries:
                    time.sleep(wait)
        else:
            raise Exception(
                f"translate_failed_after_retries; "
                f"chunk={idx}/{len(chunks)}; last_error={last_error}"
            )
        if idx < len(chunks):
            time.sleep(0.5 + random.uniform(0.0, 0.5))

    return "".join(translated_chunks).strip()


def translate_to_chinese(text, max_length=20000):
    """
    Translate English text to Chinese using Google Translate (unofficial API) as primary option.
    Falls back to the offline translate library if Google is unavailable.
    Uses chunk-based translation to handle long texts without hitting API limits.
    """
    if not re.search(r"[a-zA-Z]", text):
        return text

    text_to_translate = text[:max_length]

    try:
        result = _google_translate_with_retries(text_to_translate)
        if result:
            return result
    except Exception as e:
        print(f"Google Translate failed: {e}", file=sys.stderr)

    try:
        offline_translator = OfflineTranslator(to_lang="zh", from_lang="en")
        translated_text = offline_translator.translate(text_to_translate)
        if translated_text and "MYMEMORY WARNING" not in translated_text:
            return translated_text
    except Exception as e:
        print(f"Offline translation error: {e}", file=sys.stderr)

    return f"{text}\n\n[翻译功能: 如需翻译，请检查网络连接]"


def parse_categories(category_value: str | None) -> list[str]:
    raw_value = category_value or os.getenv("ARXIV_CATEGORY") or DEFAULT_CATEGORY
    categories = [part.strip() for part in re.split(r"[,;\s]+", raw_value) if part.strip()]
    return categories or [DEFAULT_CATEGORY]


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


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
    max_results: int = 100,
    translate: bool = False,
    include_cross_list: bool = False,
    min_results: int = 5,
) -> list[dict[str, Any]]:
    search_query = build_category_query(categories)
    fetch_limit = max(max_results, min_results, 20 if not include_cross_list else max_results)
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

    if len(selected) < min_results and len(all_papers) >= min_results:
        print(
            f"Not enough papers found in {days} day(s) ({len(selected)} papers). "
            f"Expanding to the latest {min_results} papers."
        )
        expanded = []
        for paper in all_papers:
            if not include_cross_list and paper.get("primary_category") not in category_set:
                continue
            published = datetime.strptime(paper["published"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            expanded.append((published, paper))
            if len(expanded) >= min_results:
                break
        selected = expanded

    papers = [paper for _, paper in selected[:max_results]]

    if translate:
        for paper in papers:
            print(f"Translating paper: {paper['title'][:50]}...")
            paper["translated_summary"] = translate_to_chinese(paper["summary"])
            paper["translated_title"] = translate_to_chinese(paper["title"])

    return papers


def make_empty_usage(model: str | None = None) -> dict[str, Any]:
    return {
        "model": model or "",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def extract_usage(usage: Any, model: str | None = None) -> dict[str, Any]:
    if usage is None:
        return make_empty_usage(model)
    if isinstance(usage, dict):
        prompt_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0) or 0
        completion_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0) or 0
        total_tokens = usage.get("total_tokens", 0) or prompt_tokens + completion_tokens
    else:
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or getattr(usage, "output_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", 0) or prompt_tokens + completion_tokens
    return {
        "model": model or "",
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "total_tokens": int(total_tokens or 0),
    }


def combine_usage(usages: list[dict[str, Any]], model: str | None = None) -> dict[str, Any]:
    prompt_tokens = sum(int(usage.get("prompt_tokens", 0) or 0) for usage in usages)
    completion_tokens = sum(int(usage.get("completion_tokens", 0) or 0) for usage in usages)
    total_tokens = sum(int(usage.get("total_tokens", 0) or 0) for usage in usages)
    if not total_tokens:
        total_tokens = prompt_tokens + completion_tokens
    resolved_model = model or next((usage.get("model") for usage in usages if usage.get("model")), "")
    return {
        "model": resolved_model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def normalize_model_for_pricing(model: str | None) -> str:
    model_name = (model or "").strip()
    if not model_name:
        return ""
    if model_name in MODEL_PRICES_USD_PER_1M:
        return model_name
    for known_model in sorted(MODEL_PRICES_USD_PER_1M, key=len, reverse=True):
        if model_name == known_model or model_name.startswith(f"{known_model}-"):
            return known_model
    return model_name


def get_model_prices(model: str | None) -> dict[str, float] | None:
    custom_input = os.getenv("LLM_INPUT_PRICE_USD_PER_1M")
    custom_output = os.getenv("LLM_OUTPUT_PRICE_USD_PER_1M")
    if custom_input and custom_output:
        try:
            return {"input": float(custom_input), "output": float(custom_output)}
        except ValueError:
            print("[warning] Invalid custom LLM price env vars; falling back to built-in prices.", file=sys.stderr)
    return MODEL_PRICES_USD_PER_1M.get(normalize_model_for_pricing(model))


def calculate_usage_cost_summary(usage: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    resolved_model = model or usage.get("model") or ""
    usd_cny_rate = float(os.getenv("USD_CNY_RATE", str(DEFAULT_USD_CNY_RATE)))
    prices = get_model_prices(resolved_model)
    total_tokens = int(usage.get("total_tokens", 0) or 0)
    summary = {
        "model": resolved_model,
        "total_tokens": total_tokens,
        "usd_cny_rate": usd_cny_rate,
        "cost_cny": None,
        "cost_known": False,
    }
    if total_tokens == 0:
        summary["cost_cny"] = 0.0
        summary["cost_known"] = True
        return summary
    if not prices:
        return summary
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    if prompt_tokens == 0 and completion_tokens == 0 and total_tokens > 0:
        return summary
    cost_usd = (
        prompt_tokens / 1_000_000 * prices["input"]
        + completion_tokens / 1_000_000 * prices["output"]
    )
    summary["cost_cny"] = cost_usd * usd_cny_rate
    summary["cost_known"] = True
    return summary


def heuristic_analysis(paper: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    def tokenize(text: str) -> list[str]:
        text = re.sub(r"\\[a-zA-Z]+|\$|[{}_^]", " ", text)
        return re.findall(r"[A-Za-z][A-Za-z0-9-]*", text.lower())

    stop_words = {
        "a", "an", "the", "and", "or", "of", "at", "in", "to", "with", "without",
        "for", "from", "by", "on", "as", "that", "this", "these", "those", "using",
        "based", "paper", "study", "results", "show", "shows", "present", "presents",
        "analysis", "data", "model", "models", "method", "methods", "towards", "via",
        "are", "is", "was", "were", "be", "been", "being", "can", "may", "we", "our",
    }

    scored: dict[str, int] = {}

    def add_ngrams(tokens: list[str], weight: int) -> None:
        for size in range(1, 5):
            for start in range(0, max(0, len(tokens) - size + 1)):
                words = tokens[start:start + size]
                if words[0] in stop_words or words[-1] in stop_words:
                    continue
                if all(word in stop_words for word in words):
                    continue
                if not any(len(word) > 3 and word not in stop_words for word in words):
                    continue
                phrase = " ".join(words)
                scored[phrase] = scored.get(phrase, 0) + weight * size

    add_ngrams(tokenize(paper["title"]), weight=5)
    add_ngrams(tokenize(paper["summary"]), weight=1)

    keywords = [item[0] for item in sorted(scored.items(), key=lambda pair: pair[1], reverse=True)[:8]]
    if not keywords:
        keywords = paper.get("categories", [])[:5]
    clean_query_terms = [
        keyword for keyword in keywords
        if not any(word in stop_words for word in keyword.split())
    ]
    query_terms = (clean_query_terms + keywords)[:5]
    return {
        "keywords": keywords[:8],
        "query_terms": query_terms,
        "topic_summary": paper["summary"][:500],
        "technical_focus": "未调用或无法调用 LLM，已使用本地关键词提取作为降级结果。",
        "usage": make_empty_usage(model),
    }


def parse_llm_json(content: str) -> dict[str, Any]:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def analyze_paper_with_llm(
    paper: dict[str, Any],
    model: str,
    base_url: str | None,
    api_key: str | None,
    skip_llm: bool = False,
) -> dict[str, Any]:
    if skip_llm or not api_key:
        return heuristic_analysis(paper, model=model)

    user_prompt = f"""
Analyze this arXiv paper and return strict JSON only.

Title:
{paper['title']}

Abstract:
{paper['summary']}

Primary category: {paper.get('primary_category')}
All categories: {', '.join(paper.get('categories', []))}

Required JSON schema:
{{
  "keywords": ["5-8 precise English technical keywords or phrases"],
  "query_terms": ["3-5 short English arXiv search phrases derived from the keywords"],
  "topic_summary": "用中文简洁总结这篇论文",
  "technical_focus": "用一句中文说明这篇论文为什么值得关注"
}}

Rules:
- Keep keywords specific enough for arXiv search.
- Prefer established scientific terms in English.
- Do not include Markdown, comments, or extra text.
"""
    try:
        completion = create_chat_completion(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You extract research keywords from scientific papers and produce machine-readable JSON.",
                },
                {"role": "user", "content": user_prompt},
            ],
        )
        analysis = parse_llm_json(completion["content"])
        usage = completion["usage"]
    except Exception as exc:
        print(f"[warning] LLM analysis failed for {paper['id']}: {exc}", file=sys.stderr)
        return heuristic_analysis(paper, model=model)

    keywords = [normalize_text(str(item)) for item in analysis.get("keywords", []) if normalize_text(str(item))]
    query_terms = [normalize_text(str(item)) for item in analysis.get("query_terms", []) if normalize_text(str(item))]
    if not query_terms:
        query_terms = keywords[:5]
    return {
        "keywords": keywords[:8],
        "query_terms": query_terms[:5],
        "topic_summary": normalize_text(str(analysis.get("topic_summary", ""))),
        "technical_focus": normalize_text(str(analysis.get("technical_focus", ""))),
        "usage": usage,
    }


def create_chat_completion(
    api_key: str,
    base_url: str | None,
    model: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    try:
        import openai
    except ImportError as exc:
        raise RuntimeError("openai package is not installed") from exc

    if hasattr(openai, "OpenAI"):
        client = openai.OpenAI(api_key=api_key, base_url=base_url or None)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        return {
            "content": response.choices[0].message.content or "{}",
            "usage": extract_usage(getattr(response, "usage", None), model=model),
        }

    openai.api_key = api_key
    if base_url:
        openai.api_base = base_url
    response = openai.ChatCompletion.create(
        model=model,
        messages=messages + [
            {
                "role": "system",
                "content": "Return only a valid JSON object. Do not wrap it in Markdown.",
            }
        ],
        temperature=0.2,
    )
    return {
        "content": response["choices"][0]["message"]["content"] or "{}",
        "usage": extract_usage(response.get("usage"), model=model),
    }


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


def matched_query_terms(paper: dict[str, Any], query_terms: list[str]) -> list[str]:
    haystack = f"{paper.get('title', '')} {paper.get('summary', '')}".lower()
    matches = []
    for term in query_terms:
        normalized = normalize_text(term).lower()
        if normalized and normalized in haystack:
            matches.append(term)
    return matches


def search_related_papers(
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


def format_usage_summary_text(usage_summary: dict[str, Any] | None) -> str:
    if not usage_summary:
        return ""
    total_tokens = int(usage_summary.get("total_tokens", 0) or 0)
    cost_known = usage_summary.get("cost_known", False)
    if cost_known:
        cost_text = f"¥{float(usage_summary.get('cost_cny', 0.0)):.4f}"
    else:
        cost_text = "unknown model price"
    rate = usage_summary.get("usd_cny_rate", DEFAULT_USD_CNY_RATE)
    model = usage_summary.get("model") or "unknown"
    return (
        f"Model: {model}\n"
        f"Total tokens: {total_tokens:,}\n"
        f"Estimated cost: {cost_text} (USD/CNY={rate})"
    )


def print_digest(
    digest: list[dict[str, Any]],
    categories: list[str],
    usage_summary: dict[str, Any] | None = None,
) -> None:
    current_utc_time = datetime.now(timezone.utc)
    print(f"Current UTC time: {current_utc_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 80)
    print(f"Arxiv Daily Research Digest [{', '.join(categories)}] [{len(digest)} papers]")
    print("=" * 80)
    print()

    if not digest:
        print("No papers found.")
        return

    for i, item in enumerate(digest, 1):
        paper = item["source_paper"]
        analysis = item["llm_analysis"]
        related = item["related_papers"]
        authors = paper["authors"]
        authors_display = ", ".join(authors[:5]) + (f", ... and {len(authors)-5} more authors" if len(authors) > 5 else "")
        pub_date = paper["published"].replace("T", " ").replace("Z", "")

        print(f"[{i}] {paper['title']}")
        print(f"    Published: {pub_date}")
        print(f"    Authors: {authors_display}")
        print(f"    Category: {paper.get('primary_category')}")
        print(f"    Link: {paper['link']}")
        if analysis.get("topic_summary"):
            print(f"    Summary: {analysis['topic_summary']}")
        if analysis.get("technical_focus"):
            print(f"    Focus: {analysis['technical_focus']}")
        print(f"    Keywords: {', '.join(analysis.get('keywords', []))}")
        print(f"    Query terms: {', '.join(analysis.get('query_terms', []))}")
        print("    Related papers:")
        if related:
            for related_paper in related:
                print(f"      - {related_paper['title']} ({related_paper['published'][:10]})")
                print(f"        {related_paper['link']}")
                print(f"        matched: {', '.join(related_paper.get('matched_keywords', []))}")
        else:
            print("      - None")
        print("-" * 80)
        print()

    if usage_summary:
        print("=" * 80)
        print("LLM Usage")
        print(format_usage_summary_text(usage_summary))
        print("=" * 80)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch recent arXiv papers and expand related papers by LLM keywords")
    parser.add_argument("--category", default=os.getenv("ARXIV_CATEGORY", DEFAULT_CATEGORY), help="arXiv category/categories, comma separated (default: hep-ex)")
    parser.add_argument("--days", type=int, default=int(os.getenv("ARXIV_DAYS", "3")), help="Number of days to search back")
    parser.add_argument("--max-results", type=int, default=int(os.getenv("ARXIV_MAX_RESULTS", "100")), help="Maximum source papers")
    parser.add_argument("--min-results", type=int, default=int(os.getenv("ARXIV_MIN_RESULTS", "5")), help="Expand window until this many source papers when possible")
    parser.add_argument("--related-per-paper", type=int, default=int(os.getenv("RELATED_PER_PAPER", "5")), help="Related papers to keep for each source paper")
    parser.add_argument("--related-search-limit", type=int, default=int(os.getenv("RELATED_SEARCH_LIMIT", "20")), help="arXiv candidates fetched for each related search")
    parser.add_argument("--max-query-terms", type=int, default=int(os.getenv("MAX_QUERY_TERMS", "5")), help="Maximum LLM query terms used for related search")
    parser.add_argument("--include-cross-list", action="store_true", default=parse_bool(os.getenv("INCLUDE_CROSS_LIST"), False), help="Include cross-listed papers")
    parser.add_argument("--email", action="store_true", help="Send email notification")
    parser.add_argument("--translate", action="store_true", help="Translate source abstracts and titles to Chinese")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM and use local keyword fallback")
    parser.add_argument("--llm-model", default=os.getenv("LLM_MODEL", "gpt-4o-mini"), help="OpenAI-compatible chat model")
    parser.add_argument("--llm-base-url", default=os.getenv("OPENAI_API_BASE") or os.getenv("OPENAI_BASE_URL"), help="OpenAI-compatible base URL")
    args = parser.parse_args()

    categories = parse_categories(args.category)
    papers = fetch_recent_papers(
        categories=categories,
        days=args.days,
        max_results=args.max_results,
        translate=args.translate,
        include_cross_list=args.include_cross_list,
        min_results=args.min_results,
    )
    digest = build_research_digest(
        papers=papers,
        categories=categories,
        model=args.llm_model,
        base_url=args.llm_base_url,
        api_key=os.getenv("OPENAI_API_KEY"),
        related_per_paper=args.related_per_paper,
        related_search_limit=args.related_search_limit,
        max_query_terms=args.max_query_terms,
        skip_llm=args.skip_llm,
    )
    usage = combine_usage([item.get("usage", make_empty_usage(args.llm_model)) for item in digest], model=args.llm_model)
    usage_summary = calculate_usage_cost_summary(usage, model=args.llm_model)

    print_digest(digest, categories, usage_summary=usage_summary)

    if args.email:
        send_email_notification(
            digest,
            days=args.days,
            translate=args.translate,
            category_label=", ".join(categories),
            usage_summary=usage_summary,
        )


if __name__ == "__main__":
    main()
