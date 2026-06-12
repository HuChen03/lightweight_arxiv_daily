import json
import random
import re
import sys
import time

import requests
from translate import Translator as OfflineTranslator


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
