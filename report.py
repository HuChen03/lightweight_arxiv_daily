from datetime import datetime, timezone
from typing import Any

from pricing import format_usage_summary_text


def format_authors(authors: list[str]) -> str:
    if not authors:
        return "Unknown authors"
    if len(authors) > 5:
        return ", ".join(authors[:5]) + f", ... and {len(authors) - 5} more authors"
    return ", ".join(authors)


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
        authors_display = format_authors(paper["authors"])
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
        print("    Related papers:")
        if related:
            for related_paper in related:
                print(f"      - {related_paper['title']} ({related_paper['published'][:10]})")
                print(f"        {related_paper['link']}")
                if related_paper.get("citation_count") is not None:
                    print(f"        citations: {related_paper['citation_count']:,}")
                if related_paper.get("source"):
                    print(f"        source: {related_paper['source']}")
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
