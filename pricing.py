import os
import sys
from typing import Any

from config import DEFAULT_USD_CNY_RATE


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
