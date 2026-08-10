"""OpenAI token counter backed by tiktoken (real BPE).

The spec's source layout places provider tokenizers under providers/tokenizers
and exposes a single TokenCounter abstraction. This module provides the
tiktoken implementation plus a deterministic heuristic fallback for models
tiktoken does not know, and a registry that picks the right one.
"""

from __future__ import annotations

import tiktoken

from app.providers.tokenizers.base import TokenCounter  # noqa: F401  (re-export)


class HeuristicTokenCounter:
    """Deterministic, dependency-free estimate: ~4 chars per token.

    Used as a fallback when no real tokenizer exists for a model. Not exact,
    but stable and fast, which matters for the money estimate.
    """

    def count(self, model: str, text: str) -> int:
        if not text:
            return 0
        # Common LLM heuristic: 1 token ≈ 4 characters.
        return max(1, (len(text) + 3) // 4)


class OpenAITokenCounter:
    """Counts tokens using OpenAI's actual BPE encoding for the model."""

    def count(self, model: str, text: str) -> int:
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError as exc:  # model unknown to tiktoken
            raise ValueError(f"no tiktoken encoding for model '{model}'") from exc
        return len(encoding.encode(text, disallowed_special=()))


def get_token_counter(model: str) -> TokenCounter:
    """Return the most accurate token counter available for ``model``.

    Prefers the real tiktoken encoder; falls back to the heuristic so the
    estimate never fails on an unknown model (the pricing check still gates
    support).
    """
    try:
        tiktoken.encoding_for_model(model)
    except KeyError:
        return HeuristicTokenCounter()
    return OpenAITokenCounter()
