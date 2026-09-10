"""Token reservation for visible prompts plus explicit output/framing allowance."""

from __future__ import annotations

import math
from functools import lru_cache


@lru_cache(maxsize=2)
def _encoding(name: str):
    try:
        import tiktoken

        return tiktoken.get_encoding(name)
    except Exception:
        # Offline first use can lack the downloaded vocabulary. Keep the old
        # conservative byte bound, rather than losing the ability to fail closed.
        return None


def reserve_prompt_tokens(text: str, *, model: object = None) -> int:
    native = isinstance(model, str) and model.startswith("gpt-")
    encoding = _encoding("o200k_base" if native else "cl100k_base")
    if encoding is None:
        return len(text.encode("utf-8")) + 2048
    count = len(encoding.encode(text, disallowed_special=()))
    return math.ceil(count * (1.2 if native else 1.5)) + 768
