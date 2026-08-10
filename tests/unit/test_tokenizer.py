"""Unit tests for the tokenizer implementations."""

from __future__ import annotations

from app.providers.tokenizers.openai_tokenizer import (
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


class TestOpenAI:
    def test_known_model(self):
        # gpt-4o uses cl100k_base; "hello world" is a small positive count.
        count = OpenAITokenCounter().count("gpt-4o", "hello world")
        assert isinstance(count, int)
        assert count > 0

    def test_unknown_model_raises(self):
        import pytest

        with pytest.raises(ValueError):
            OpenAITokenCounter().count("definitely-not-a-real-model-xyz", "hi")


class TestRegistry:
    def test_known_model_prefers_tiktoken(self):
        tc = get_token_counter("gpt-4o")
        assert isinstance(tc, OpenAITokenCounter)

    def test_unknown_model_falls_back(self):
        tc = get_token_counter("custom-llama-9000")
        assert isinstance(tc, HeuristicTokenCounter)
