"""Query normalization for search pipeline."""

import re
import unicodedata


def normalize_query(query: str) -> str:
    """Normalize a search query.

    Steps:
    1. Unicode NFC normalization
    2. Strip leading/trailing whitespace
    3. Collapse internal whitespace to single space
    4. Remove redundant punctuation
    """
    text = unicodedata.normalize("NFC", query)
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    # Keep identifier punctuation used by technical terms such as pydantic-ai
    # and with_structured_output(); other punctuation remains query noise.
    text = re.sub(r"[^\w\s一-鿿\-()]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
