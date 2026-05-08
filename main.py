import argparse
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from email_notifier import send_email_notification
import urllib.parse
import os
import json
from translate import Translator as OfflineTranslator


ARXIV_API = "http://export.arxiv.org/api/query"

def translate_to_chinese(text, max_length=4000):
    """
    Translate English text to Chinese using Microsoft Translator API as primary option.
    Falls back to the translate library if Microsoft API is unavailable.
    Implements chunk-based translation to avoid rate limits.
    """
    import re

    # Check if text is mostly English (contains Latin characters)
    if not re.search(r'[a-zA-Z]', text):
        # Already appears to be Chinese or non-Latin
        return text

    # Limit the length to avoid hitting API limits
    text_to_translate = text[:max_length]

    # Split text into sentences to perform chunk-based translation
    def split_into_sentences(text):
        # Split by sentence endings (., !, ?, etc.) but keep the delimiters
        sentences = re.split(r'(?<=[.!?。！？])\s+', text.strip())
        # Clean up empty strings and join sentences with appropriate spacing
        sentences = [s.strip() for s in sentences if s.strip()]
        return sentences

    def translate_chunk(chunk_text, method='microsoft'):
        """Translate a single chunk of text"""
        if method == 'microsoft':
            subscription_key = os.getenv('MICROSOFT_TRANSLATOR_KEY')
            region = os.getenv('MICROSOFT_TRANSLATOR_REGION', 'global')

            if not subscription_key:
                return None  # Skip Microsoft if no key

            try:
                # Microsoft Translator API endpoint
                endpoint = "https://api.cognitive.microsofttranslator.com"
                path = '/translate'
                constructed_url = endpoint + path

                params = {
                    'api-version': '3.0',
                    'from': 'en',
                    'to': 'zh-Hans'  # Simplified Chinese
                }

                headers = {
                    'Ocp-Apim-Subscription-Key': subscription_key,
                    'Ocp-Apim-Subscription-Region': region,
                    'Content-type': 'application/json',
                    'X-ClientTraceId': str(hash(chunk_text))[:32]  # Optional trace ID
                }

                body = [{
                    'text': chunk_text
                }]

                response = requests.post(constructed_url, params=params, headers=headers, json=body)

                if response.status_code == 200:
                    result = response.json()
                    if result and len(result) > 0 and 'translations' in result[0]:
                        translated_text = result[0]['translations'][0].get('text', '')
                        return translated_text
            except Exception as e:
                print(f"Microsoft Translator error for chunk: {e}")
                return None
        else:  # offline translator
            try:
                offline_translator = OfflineTranslator(to_lang="zh", from_lang="en")
                translated_text = offline_translator.translate(chunk_text)
                if "MYMEMORY WARNING" not in translated_text:  # Filter out warnings from the service
                    return translated_text
            except Exception as e:
                print(f"Offline translation error for chunk: {e}")
                return None
        return None

    # Perform chunk-based translation
    sentences = split_into_sentences(text_to_translate)

    if len(sentences) <= 1:
        # If text is short enough or cannot be split further, translate as a whole
        # Try Microsoft first
        result = translate_chunk(text_to_translate, 'microsoft')
        if result is not None:
            return result

        # Fallback to offline translator
        result = translate_chunk(text_to_translate, 'offline')
        if result is not None:
            return result
    else:
        # Translate sentence by sentence
        translated_parts = []

        for sentence in sentences:
            # First try Microsoft API
            translated_sentence = translate_chunk(sentence, 'microsoft')

            if translated_sentence is None:
                # If Microsoft fails, try offline translator
                translated_sentence = translate_chunk(sentence, 'offline')

            if translated_sentence is not None:
                translated_parts.append(translated_sentence)
            else:
                # If both methods fail, keep the original sentence with a note
                translated_parts.append(f"{sentence}\n\n[翻译失败，请检查网络连接]")

        # Join translated parts back together
        return ' '.join(translated_parts)

    # If all methods fail, return original text with note
    return f"{text}\n\n[翻译功能: 如需完整翻译，请设置 MICROSOFT_TRANSLATOR_KEY 环境变量或检查网络连接]"

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

    # If we have fewer than 3 papers or fewer than 10 papers, expand until we have at least 10
    if len(papers_in_original_window) < 3 or len(papers_in_original_window) < 10:
        print(f"Not enough papers found ({len(papers_in_original_window)} papers). Expanding time window to reach at least 10 papers...")

        # Include more papers until we reach at least 10
        if len(all_papers) >= 10:
            # Take the 10 most recent papers
            selected_papers = all_papers[:10]
        else:
            # If there are fewer than 10 papers total, take all of them
            selected_papers = all_papers

        # Convert back to the format expected
        papers = [data for _, data in selected_papers[:max_results]]
    else:
        # If we have 3 or more papers but 10 or more, just return those in the original window
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
    current_date_utc = datetime.now(timezone.utc).strftime("%y.%m.%d")

    if args.translate:
        print(f"📚 Arxiv Hep-ex Daily Paper Digest {current_date_utc} [{len(papers)} papers, 中英文对照]")
    else:
        print(f"📚 Arxiv Hep-ex Daily Paper Digest {current_date_utc} [{len(papers)} papers]")
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

        # Display title and possibly translated title
        if args.translate and 'translated_title' in p:
            print(f"[{i}] {p['translated_title']}")
            print(f"    Original Title: {p['title']}")
        else:
            print(f"[{i}] {p['title']}")

        print(f"    📅 Published: {pub_date}")
        print(f"    👤 Authors: {authors_display}")

        # Display abstract and possibly translated abstract
        if args.translate and 'translated_summary' in p:
            print(f"    📝 Abstract (中文): {p['translated_summary']}")
            print(f"    📝 Abstract (English): {p['summary']}")
        else:
            print(f"    📝 Abstract: {p['summary']}")

        print(f"    🔗 Link: {p['link']}")
        print("-" * 80)
        print()

    # 发送邮件通知
    if args.email:
        send_email_notification(papers, days=args.days, translate=args.translate)
