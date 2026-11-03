"""Unit tests for the tokenizer implementations."""

from __future__ import annotations

import pytest
import tiktoken

from app.providers.tokenizers import openai_tokenizer
from app.providers.tokenizers.openai_tokenizer import (
    AutoTokenCounter,
    HeuristicTokenCounter,
    OpenAITokenCounter,
    get_token_counter,
)


class TestHeuristic:
    def test_empty(self):
        assert HeuristicTokenCounter().count("any", "") == 0

    def test_roughly_four_chars(self):
        assert HeuristicTokenCounter().count("m", "hello") == 2  # (5+3)//4
        assert HeuristicTokenCounter().count("m", "a") == 1

    def test_unicode(self):
        assert HeuristicTokenCounter().count("m", "héllo→") > 0

    def test_long(self):
        assert HeuristicTokenCounter().count("m", "x" * 4000) == 1000


def _bpe_available() -> bool:
    """tiktoken downloads encodings on first use; skip real-BPE tests when offline."""
    try:
        tiktoken.encoding_for_model("gpt-4o")
    except Exception:
        return False
    return True


needs_bpe = pytest.mark.skipif(not _bpe_available(), reason="tiktoken encoding not available")


class TestOpenAI:
    @needs_bpe
    def test_known_model(self):
        # gpt-4o uses cl100k_base; "hello world" is a small positive count.
        count = OpenAITokenCounter().count("gpt-4o", "hello world")
        assert isinstance(count, int)
        assert count > 0

    def test_unknown_model_raises(self):
        with pytest.raises(ValueError):
            OpenAITokenCounter().count("definitely-not-a-real-model-xyz", "hi")


class TestRegistry:
    @needs_bpe
    def test_known_model_prefers_tiktoken(self):
        tc = get_token_counter("gpt-4o")
        assert isinstance(tc, OpenAITokenCounter)

    def test_unknown_model_falls_back(self):
        tc = get_token_counter("custom-llama-9000")
        assert isinstance(tc, HeuristicTokenCounter)


class TestAuto:
    def test_unknown_model_uses_heuristic(self):
        assert AutoTokenCounter().count("custom-llama-9000", "hello") == 2

    @needs_bpe
    def test_uses_requested_model_not_a_constant(self):
        # "hello world" is 2 BPE tokens but 3 by the chars/4 heuristic.
        assert AutoTokenCounter().count("gpt-4o", "hello world") == 2

    def test_load_failure_falls_back_then_retries_later(self, monkeypatch):
        calls = []

        def boom(model):
            calls.append(model)
            raise ConnectionError("no network")

        monkeypatch.setattr(openai_tokenizer.tiktoken, "encoding_for_model", boom)
        counter = AutoTokenCounter()
        assert counter.count("gpt-4o", "hello world") == 3  # heuristic: (11+3)//4 -> 3
        assert counter.count("gpt-4o", "hello world") == 3
        assert calls == ["gpt-4o"]  # second call skipped the retry window
        counter._retry_at["gpt-4o"] = 0.0
        counter.count("gpt-4o", "hello world")
        assert calls == ["gpt-4o", "gpt-4o"]
