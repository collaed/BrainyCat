"""Robust LLM output parsing — 5-layer JSON fallback inspired by Beever Atlas."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_llm_json(text: str) -> Any:
    """Parse JSON from LLM output with 5-layer fallback.

    1. Direct parse
    2. Fence stripping (```json ... ```)
    3. Brace/bracket extraction
    4. Control char sanitization
    5. Char-by-char recovery
    """
    if not text or not text.strip():
        return None

    # Layer 1: Direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Layer 2: Strip markdown fences
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # Layer 3: Extract first JSON array or object
    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = text.find(start_char)
        if start >= 0:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == start_char:
                    depth += 1
                elif text[i] == end_char:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except (json.JSONDecodeError, ValueError):
                            break

    # Layer 4: Sanitize control characters
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    cleaned = cleaned.replace("'", '"')  # single → double quotes
    for attempt in [cleaned, cleaned.strip()]:
        start = attempt.find("[") if "[" in attempt else attempt.find("{")
        if start >= 0:
            try:
                return json.loads(attempt[start:])
            except (json.JSONDecodeError, ValueError):
                pass

    # Layer 5: Extract key-value pairs manually
    pairs = re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', text)
    if pairs:
        return dict(pairs)

    return None
