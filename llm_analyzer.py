import json
import re
import sys
from typing import Any

from pricing import extract_usage, make_empty_usage
from text_utils import normalize_text


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
