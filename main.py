import argparse
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from email_notifier import send_email_notification
import urllib.parse
import os
import json
import sys
import random
import time
import re
from translate import Translator as OfflineTranslator


ARXIV_API = "http://export.arxiv.org/api/query"

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
    # Check if text is already Chinese (no Latin characters)
    if not re.search(r'[a-zA-Z]', text):
        return text

    # Allow long text — the chunking handles splitting internally
    text_to_translate = text[:max_length]

    # Primary: Google Translate
    try:
        result = _google_translate_with_retries(text_to_translate)
        if result:
            return result
    except Exception as e:
        print(f"Google Translate failed: {e}", file=sys.stderr)

    # Fallback: offline translator
    try:
        offline_translator = OfflineTranslator(to_lang="zh", from_lang="en")
        translated_text = offline_translator.translate(text_to_translate)
        if translated_text and "MYMEMORY WARNING" not in translated_text:
            return translated_text
    except Exception as e:
        print(f"Offline translation error: {e}", file=sys.stderr)

    return f"{text}\n\n[翻译功能: 如需翻译，请检查网络连接]"

def fetch_recent_hepex(days=3, max_results=100, translate=False):
    params = {
        "search_query": "cat:hep-ex",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending"
    }

    response = requests.get(ARXIV_API, params=params)
    feed = feedparser.parse(response.text)

    # Start with the original time window
    original_cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Get all papers within the feed sorted by date (already sorted by the API)
    all_papers = []
    for entry in feed.entries:
        published = datetime.strptime(entry.published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

        paper_data = {
            "title": entry.title,
            "authors": [a.name for a in entry.authors],
            "link": entry.link,
            "published": entry.published,
            "summary": entry.summary  # Full abstract
        }

        # Add translated content if requested
        if translate:
            print(f"Translating paper: {entry.title[:50]}...")  # Inform user of progress
            paper_data["translated_summary"] = translate_to_chinese(entry.summary)
            paper_data["translated_title"] = translate_to_chinese(entry.title)

        all_papers.append((published, paper_data))

    # Sort by date descending (most recent first)
    all_papers.sort(key=lambda x: x[0], reverse=True)

    # First, get papers within the original time window
    papers_in_original_window = [(pub, data) for pub, data in all_papers if pub >= original_cutoff]

    # If we have at least 3 papers and at least 10 papers, return them
    if len(papers_in_original_window) >= 3 and len(papers_in_original_window) >= 10:
        papers = [data for _, data in papers_in_original_window[:max_results]]
        return papers

    # If we have fewer than 3 papers or fewer than 5 papers, expand until we have at least 5
    if len(papers_in_original_window) < 3 or len(papers_in_original_window) < 5:
        print(f"Not enough papers found ({len(papers_in_original_window)} papers). Expanding time window to reach at least 5 papers...")

        # Include more papers until we reach at least 5
        if len(all_papers) >= 5:
            # Take the 5 most recent papers
            selected_papers = all_papers[:5]
            # Print how far back in time we had to go
            oldest_paper_date = selected_papers[-1][0]  # Last paper is oldest among selected
            original_request_end = original_cutoff
            if oldest_paper_date < original_request_end:
                time_diff = original_request_end - oldest_paper_date
                hours_extended = int(time_diff.total_seconds() / 3600)
                print(f"Time window extended to include papers from {hours_extended} hours ago to satisfy minimum count.")
        else:
            # If there are fewer than 5 papers total, take all of them
            selected_papers = all_papers
            if all_papers:  # If there are any papers at all
                oldest_paper_date = all_papers[-1][0]
                original_request_end = original_cutoff
                if oldest_paper_date < original_request_end:
                    time_diff = original_request_end - oldest_paper_date
                    hours_extended = int(time_diff.total_seconds() / 3600)
                    print(f"Time window extended to include papers from {hours_extended} hours ago (only {len(all_papers)} papers available total).")

        # Convert back to the format expected
        papers = [data for _, data in selected_papers[:max_results]]
    else:
        # If we have 3 or more papers and at least 5, just return those in the original window
        papers = [data for _, data in papers_in_original_window[:max_results]]

    return papers


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch recent hep-ex papers from arXiv")
    parser.add_argument("--days", type=int, default=3, help="Number of days to search back (default: 3)")
    parser.add_argument("--max-results", type=int, default=100, help="Maximum number of results (default: 100)")
    parser.add_argument("--email", action="store_true", help="Send email notification")
    parser.add_argument("--translate", action="store_true", help="Translate abstracts and titles to Chinese")
    args = parser.parse_args()

    papers = fetch_recent_hepex(days=args.days, max_results=args.max_results, translate=args.translate)

    from datetime import datetime, timezone
    current_utc_time = datetime.now(timezone.utc)
    print(f"Current UTC time: {current_utc_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 80)
    from zoneinfo import ZoneInfo
    european_tz = ZoneInfo("Europe/Berlin")
    current_date_full_year = datetime.now(european_tz).strftime("%Y.%m.%d")

    if args.translate:
        print(f"📚 Arxiv Hep-ex Daily Paper Digest {current_date_full_year} [{len(papers)} papers, 中英文对照]")
    else:
        print(f"📚 Arxiv Hep-ex Daily Paper Digest {current_date_full_year} [{len(papers)} papers]")
    print("=" * 80)
    print()

    for i, p in enumerate(papers, 1):
        # 格式化日期
        pub_date = p['published'].replace("T", " ").replace("Z", "")

        # Format authors - show only first few and indicate if there are more
        author_list = p['authors']
        if len(author_list) > 5:
            authors_display = ', '.join(author_list[:5]) + f', ... and {len(author_list)-5} more authors'
        else:
            authors_display = ', '.join(author_list)

        if args.translate and 'translated_title' in p:
            # ── 中文 ──
            print(f"[{i} - 中文]")
            print(f"    标题: {p['translated_title']}")
            print(f"    摘要: {p['translated_summary']}")
            print()
            # ── English ──
            print(f"[{i} - English]")
            print(f"    Title: {p['title']}")
            print(f"    📅 Published: {pub_date}")
            print(f"    👤 Authors: {authors_display}")
            print(f"    📝 Abstract: {p['summary']}")
            print(f"    🔗 Link: {p['link']}")
        else:
            print(f"[{i}] {p['title']}")
            print(f"    📅 Published: {pub_date}")
            print(f"    👤 Authors: {authors_display}")
            print(f"    📝 Abstract: {p['summary']}")
            print(f"    🔗 Link: {p['link']}")

        print("-" * 80)
        print()

    # 发送邮件通知
    if args.email:
        # Determine if time window was extended
        original_cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
        original_papers_count = sum(1 for p in papers
                                   if datetime.strptime(p['published'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) >= original_cutoff)
        time_window_extended = original_papers_count < 3 or original_papers_count < 5

        send_email_notification(papers, days=args.days, translate=args.translate, time_window_extended=time_window_extended)
