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


class _FakeEncoding:
    def encode(self, text, disallowed_special=()):
        return text.split()


def _fake_tiktoken(monkeypatch):
    import tiktoken

    def encoding_for_model(model):
        if model.startswith("gpt-"):
            return _FakeEncoding()
        raise KeyError(model)

    monkeypatch.setattr(tiktoken, "encoding_for_model", encoding_for_model)


class TestModelRouting:
    def test_routes_known_model_to_tiktoken(self, monkeypatch):
        from app.providers.tokenizers.openai_tokenizer import ModelRoutingTokenCounter

        _fake_tiktoken(monkeypatch)
        # 5 words via the fake BPE; the heuristic would say (26+3)//4 = 7.
        assert ModelRoutingTokenCounter().count("gpt-4o", "Explain the Decimal money math") == 5

    def test_routes_unknown_model_to_heuristic(self, monkeypatch):
        from app.providers.tokenizers.openai_tokenizer import ModelRoutingTokenCounter

        _fake_tiktoken(monkeypatch)
        assert ModelRoutingTokenCounter().count("custom-llama-9000", "hello") == 2

    async def test_estimator_dependency_counts_with_request_model(self, monkeypatch):
        # Regression: the API passed the provider name ("openai") as the model, so tiktoken
        # was never used and every estimate came from the 4-chars-per-token heuristic.
        from app.api.dependencies import estimator_dep

        _fake_tiktoken(monkeypatch)
        estimator = await estimator_dep(session=None)
        assert estimator._token_counter.count("gpt-4o", "one two three") == 3


def test_routing_falls_back_when_encoding_cannot_load(monkeypatch):
    import tiktoken

    from app.providers.tokenizers.openai_tokenizer import ModelRoutingTokenCounter

    def offline(model):
        raise OSError("no network")

    monkeypatch.setattr(tiktoken, "encoding_for_model", offline)
    assert ModelRoutingTokenCounter().count("gpt-4o", "hello") == 2
