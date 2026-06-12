import os
import re
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_FILE)

DEFAULT_CATEGORY = "hep-ex"
DEFAULT_USD_CNY_RATE = 7.2


def parse_categories(category_value: str | None) -> list[str]:
    raw_value = category_value or os.getenv("ARXIV_CATEGORY") or DEFAULT_CATEGORY
    categories = [part.strip() for part in re.split(r"[,;\s]+", raw_value) if part.strip()]
    return categories or [DEFAULT_CATEGORY]


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}
