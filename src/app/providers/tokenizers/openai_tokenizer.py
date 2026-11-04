"""OpenAI token counter backed by tiktoken (real BPE).

The spec's source layout places provider tokenizers under providers/tokenizers
and exposes a single TokenCounter abstraction. This module provides the
tiktoken implementation plus a deterministic heuristic fallback for models
tiktoken does not know, and a registry that picks the right one.
"""

from __future__ import annotations

import time

import structlog
import tiktoken

from app.providers.tokenizers.base import TokenCounter  # noqa: F401  (re-export)

logger = structlog.get_logger(__name__)

# After a failed encoding load (e.g. no network for the first tiktoken
# download), skip real BPE for this long before trying again.
_RETRY_AFTER_SECONDS = 60.0


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


class AutoTokenCounter:
    """Per-request counter: real BPE when available, heuristic otherwise.

    The model comes from each request, so ``gpt-4o`` is counted with its real
    encoding. Unknown models fall back to the heuristic for good. A failure to
    load the encoding (tiktoken downloads it on first use unless
    ``TIKTOKEN_CACHE_DIR`` is pre-warmed) falls back too, and is retried after
    ``_RETRY_AFTER_SECONDS`` so a slow network never fails or stalls estimates.
    """

    def __init__(self) -> None:
        self._heuristic = HeuristicTokenCounter()
        self._unknown_models: set[str] = set()
        self._retry_at: dict[str, float] = {}

    def count(self, model: str, text: str) -> int:
        if model not in self._unknown_models and time.monotonic() >= self._retry_at.get(model, 0.0):
            try:
                return OpenAITokenCounter().count(model, text)
            except ValueError:
                self._unknown_models.add(model)
            except Exception as exc:
                self._retry_at[model] = time.monotonic() + _RETRY_AFTER_SECONDS
                logger.warning("tiktoken_unavailable_using_heuristic", model=model, error=str(exc))
        return self._heuristic.count(model, text)
