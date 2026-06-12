import argparse
import os

from arxiv_client import fetch_recent_papers
from config import DEFAULT_CATEGORY, parse_bool, parse_categories
from digest import build_research_digest
from email_notifier import send_email_notification
from pricing import calculate_usage_cost_summary, combine_usage, make_empty_usage
from report import print_digest
from translation import translate_to_chinese


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch recent arXiv papers and expand related papers by LLM keywords")
    parser.add_argument("--category", default=os.getenv("ARXIV_CATEGORY", DEFAULT_CATEGORY), help="arXiv category/categories, comma separated (default: hep-ex)")
    parser.add_argument("--days", type=int, default=int(os.getenv("ARXIV_DAYS", "3")), help="Number of days to search back")
    parser.add_argument("--max-results", type=int, default=int(os.getenv("ARXIV_MAX_RESULTS", "10")), help="Maximum source papers")
    parser.add_argument("--related-per-paper", type=int, default=int(os.getenv("RELATED_PER_PAPER", "5")), help="Related papers to keep for each source paper")
    parser.add_argument("--email", action="store_true", help="Send email notification")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM and use local keyword fallback")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    categories = parse_categories(args.category)
    llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    llm_base_url = os.getenv("OPENAI_API_BASE") or os.getenv("OPENAI_BASE_URL")
    translate_titles = parse_bool(os.getenv("TRANSLATE_TITLES"), False)
    papers = fetch_recent_papers(
        categories=categories,
        days=args.days,
        max_results=args.max_results,
        translate=translate_titles,
        include_cross_list=parse_bool(os.getenv("INCLUDE_CROSS_LIST"), False),
    )
    digest = build_research_digest(
        papers=papers,
        categories=categories,
        model=llm_model,
        base_url=llm_base_url,
        api_key=os.getenv("OPENAI_API_KEY"),
        related_per_paper=args.related_per_paper,
        related_search_limit=int(os.getenv("RELATED_SEARCH_LIMIT", "20")),
        max_query_terms=int(os.getenv("MAX_QUERY_TERMS", "5")),
        skip_llm=args.skip_llm,
    )
    usage = combine_usage([item.get("usage", make_empty_usage(llm_model)) for item in digest], model=llm_model)
    usage_summary = calculate_usage_cost_summary(usage, model=llm_model)

    print_digest(digest, categories, usage_summary=usage_summary)

    if args.email:
        send_email_notification(
            digest,
            days=args.days,
            translate=translate_titles,
            category_label=", ".join(categories),
            usage_summary=usage_summary,
        )


if __name__ == "__main__":
    main()
