"""Unit tests for the Phase 16 Prometheus metrics helpers."""

from __future__ import annotations

from app.core.metrics import Metrics


def test_record_usage_increments_counters():
    m = Metrics(enabled=True)
    m.record_usage(
        provider="openai",
        model="gpt-4o",
        input_tokens=100,
        output_tokens=50,
        actual_cost=0.0015,
        estimated_cost=0.0020,
    )
    assert m._input_tokens.labels("openai", "gpt-4o")._value.get() == 100
    assert m._output_tokens.labels("openai", "gpt-4o")._value.get() == 50
    assert m._cost.labels("openai", "gpt-4o")._value.get() == 0.0015
    assert m._estimated_cost.labels("openai", "gpt-4o")._value.get() == 0.0020


def test_record_budget_rejection():
    m = Metrics(enabled=True)
    m.record_budget_rejection(provider="openai", model="gpt-4o", reason="BLOCK")
    assert m._budget_rejections.labels("openai", "gpt-4o", "BLOCK")._value.get() == 1


def test_record_anomaly():
    m = Metrics(enabled=True)
    m.record_anomaly(provider="openai", model="gpt-4o")
    assert m._anomalies.labels("openai", "gpt-4o")._value.get() == 1


def test_record_request_histogram():
    m = Metrics(enabled=True)
    m.record_request(
        duration_seconds=0.5,
        endpoint="/v1/generate",
        status=200,
        provider="openai",
        model="gpt-4o",
    )
    samples = {
        s.name: s.value
        for s in m._requests.collect()[0].samples
        if s.labels
        == {
            "provider": "openai",
            "model": "gpt-4o",
            "endpoint": "/v1/generate",
            "status": "200",
        }
    }
    assert samples["llm_requests_total"] == 1
    # Histogram observes once; _sum reflects the duration.
    hist_samples = {
        s.name: s.value
        for s in m._duration.collect()[0].samples
        if s.labels.get("provider") == "openai"
    }
    assert hist_samples["llm_request_duration_seconds_sum"] == 0.5


def test_disabled_metrics_noop():
    m = Metrics(enabled=False)
    m.record_usage(
        provider="openai",
        model="gpt-4o",
        input_tokens=10,
        output_tokens=5,
        actual_cost=0.1,
        estimated_cost=0.2,
    )
    # No-op: counters stay at zero even though definitions render.
    assert m._input_tokens.labels("openai", "gpt-4o")._value.get() == 0
    assert m._cost.labels("openai", "gpt-4o")._value.get() == 0


def test_render_prometheus_format():
    m = Metrics(enabled=True)
    m.record_anomaly(provider="openai", model="gpt-4o")
    text = m.render().decode()
    assert "llm_cost_anomaly_total" in text
    assert "llm_requests_total" in text
    # Prometheus text format has HELP/TYPE lines.
    assert "# HELP" in text
