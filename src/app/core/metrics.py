"""Prometheus metrics + lightweight span emission (PRD Phase 16, §35).

Exposes the exact PRD metric names on a private registry, with helper methods
so services never touch ``prometheus_client`` directly. A ``Span`` context
manager binds span name + duration to structlog contextvars and logs a
``span_completed`` event — the PRD's expected trace chain, without OTel.

No raw user_id labels (PRD §35: avoid uncontrolled high-cardinality labels).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog
from prometheus_client import Counter, Histogram, generate_latest
from prometheus_client.registry import CollectorRegistry

from app.core.config import get_settings

logger = structlog.get_logger("app.metrics")

_DEFAULT_LABELS = ["provider", "model"]


class Metrics:
    """Prometheus metrics registry + helper methods (PRD §35 metric names).

    Uses a private CollectorRegistry so tests can construct fresh Metrics
    instances without colliding with the module singleton or the global
    prometheus_client default registry.
    """

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._registry = CollectorRegistry()
        self._requests = Counter(
            "llm_requests_total",
            "Total LLM-related HTTP requests.",
            ["provider", "model", "endpoint", "status"],
            registry=self._registry,
        )
        self._input_tokens = Counter(
            "llm_input_tokens_total",
            "Total billed input tokens.",
            _DEFAULT_LABELS,
            registry=self._registry,
        )
        self._output_tokens = Counter(
            "llm_output_tokens_total",
            "Total billed output tokens.",
            _DEFAULT_LABELS,
            registry=self._registry,
        )
        self._cost = Counter(
            "llm_cost_total",
            "Total actual cost (USD).",
            _DEFAULT_LABELS,
            registry=self._registry,
        )
        self._estimated_cost = Counter(
            "llm_estimated_cost_total",
            "Total estimated cost (USD).",
            _DEFAULT_LABELS,
            registry=self._registry,
        )
        self._budget_rejections = Counter(
            "llm_budget_rejections_total",
            "Total budget rejections (BLOCK / non-ALLOW).",
            ["provider", "model", "reason"],
            registry=self._registry,
        )
        self._anomalies = Counter(
            "llm_cost_anomaly_total",
            "Total cost anomaly alerts.",
            _DEFAULT_LABELS,
            registry=self._registry,
        )
        self._duration = Histogram(
            "llm_request_duration_seconds",
            "Request latency in seconds.",
            ["provider", "model", "endpoint", "status"],
            registry=self._registry,
        )

    # --- request-level -------------------------------------------------------

    def record_request(
        self,
        *,
        duration_seconds: float,
        endpoint: str,
        status: int,
        provider: str = "",
        model: str = "",
    ) -> None:
        if not self._enabled:
            return
        self._requests.labels(provider, model, endpoint, str(status)).inc()
        self._duration.labels(provider, model, endpoint, str(status)).observe(duration_seconds)

    # --- usage / cost --------------------------------------------------------

    def record_usage(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        actual_cost: float,
        estimated_cost: float,
    ) -> None:
        if not self._enabled:
            return
        self._input_tokens.labels(provider, model).inc(input_tokens)
        self._output_tokens.labels(provider, model).inc(output_tokens)
        self._cost.labels(provider, model).inc(actual_cost)
        self._estimated_cost.labels(provider, model).inc(estimated_cost)

    # --- budget / anomaly ----------------------------------------------------

    def record_budget_rejection(self, *, provider: str, model: str, reason: str) -> None:
        if not self._enabled:
            return
        self._budget_rejections.labels(provider, model, reason).inc()

    def record_anomaly(self, *, provider: str, model: str) -> None:
        if not self._enabled:
            return
        self._anomalies.labels(provider, model).inc()

    # --- serialization -------------------------------------------------------

    def render(self) -> bytes:
        return generate_latest(self._registry)


# Module-level singleton so services call Metrics.record_*() without DI churn.
metrics = Metrics(enabled=get_settings().metrics_enabled)


@contextmanager
def span(name: str, **fields: Any) -> Iterator[None]:
    """Time a named span, bind it to structlog contextvars, log completion.

    Matches the PRD trace chain (Tokenization, Pricing Lookup, Cost Estimation,
    Budget Evaluation, LLM Provider, Usage Reconciliation, Persistence).
    """
    start = time.perf_counter()
    structlog.contextvars.bind_contextvars(span=name)
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        structlog.contextvars.unbind_contextvars("span")
        logger.info(
            "span_completed",
            span=name,
            span_duration_seconds=round(duration, 6),
            **fields,
        )
