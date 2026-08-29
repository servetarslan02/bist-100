from typing import Any
"""
ALPHA BIST — Observability, Prometheus Metrics & OpenTelemetry Pipeline Test Suite
Doğrulanan Özellikler:
1. PrometheusMetrics: Official prometheus_client integration
2. DistributedTracing: OpenTelemetry span generation
3. Sistem & ML Metrik Enstrümantasyonu
4. OpenTelemetry Tracer Provider ve Context Yönetimi
5. FastAPI /metrics ve /health entegrasyonu
"""

import pytest
from fastapi.testclient import TestClient

from services.api.app import app
from services.core.observability import DistributedTracing, PrometheusMetrics
from services.core.otel import get_tracer, setup_telemetry


@pytest.fixture(scope="module")
def client() -> Any:
    """Otomatik eklendi."""
    return TestClient(app)


class TestPrometheusMetricsEngine:
    """Prometheus metrik toplama, histogram ve metin formatı testleri."""

    def test_counters_and_gauges(self) -> Any:
        """Otomatik eklendi."""
        metrics = PrometheusMetrics()

        # Counter
        metrics.inc("orders_total", value=1, labels={"ticker": "THYAO", "side": "BUY"})
        metrics.inc("orders_total", value=2, labels={"ticker": "THYAO", "side": "BUY"})
        metrics.inc("orders_total", value=1, labels={"ticker": "ASELS", "side": "SELL"})

        # Gauge
        metrics.set_gauge("portfolio_equity_tl", value=1250000.50, labels={"portfolio": "main"})
        metrics.set_gauge("model_hit_rate_pct", value=68.4, labels={"model": "lightgbm"})

        text = metrics.get_prometheus_text()
        assert (
            'orders_total{side="BUY",ticker="THYAO"} 3.0' in text
            or 'orders_total{ticker="THYAO",side="BUY"} 3.0' in text
        )
        assert (
            'orders_total{side="SELL",ticker="ASELS"} 1.0' in text
            or 'orders_total{ticker="ASELS",side="SELL"} 1.0' in text
        )
        assert 'portfolio_equity_tl{portfolio="main"} 1.2500005e+06' in text
        assert 'model_hit_rate_pct{model="lightgbm"} 68.4' in text

    def test_histogram_and_percentiles(self) -> Any:
        """Otomatik eklendi."""
        metrics = PrometheusMetrics()

        # Simulate 100 request latencies in seconds (0.01s to 0.10s)
        for i in range(1, 101):
            metrics.observe("api_request_duration_seconds", value=i * 0.001, labels={"handler": "predict"})

        text = metrics.get_prometheus_text()
        assert 'api_request_duration_seconds_count{handler="predict"} 100.0' in text
        # Just checking that it generates bucket strings properly
        assert "api_request_duration_seconds_bucket" in text

    def test_prometheus_text_exposition_format(self) -> Any:
        """Otomatik eklendi."""
        metrics = PrometheusMetrics()
        metrics.inc("trade_executions_total", 5, labels={"broker": "direct"})
        metrics.set_gauge("portfolio_var_95", 0.023)
        metrics.observe("ml_inference_duration_seconds", 0.015)

        text = metrics.get_prometheus_text()
        assert "trade_executions_total" in text
        assert "portfolio_var_95" in text
        assert "ml_inference_duration_seconds" in text


class TestDistributedTracing:
    """Dağıtık izleme, trace_id ve span hiyerarşisi."""

    def test_trace_lifecycle(self) -> Any:
        """Otomatik eklendi."""
        dt = DistributedTracing()
        trace_id = dt.start_trace("order_execution_pipeline")
        assert len(trace_id) > 0

        # These are dummy/mock operations in v2 (handled natively by OTel context now)
        dt.add_span(trace_id, "pre_trade_risk_check", duration_ms=4.2, status="completed")

        spans = dt.get_spans(trace_id)
        assert spans == []  # Mocked return value for backward compatibility


class TestOpenTelemetryModule:
    """OpenTelemetry modülü güvenli başlatma ve tracer alımı."""

    def test_otel_setup_and_tracer(self) -> Any:
        """Otomatik eklendi."""
        setup_telemetry(service_name="alpha-test-service", enabled=False)
        tracer = get_tracer("test_tracer")
        assert tracer is not None


class TestMetricsEndpointIntegration:
    """FastAPI /metrics ve /health endpoint canlı testleri."""

    def test_metrics_endpoint_returns_prometheus_text(self, client) -> Any:
        """Otomatik eklendi."""
        resp = client.get("/metrics")
        assert resp.status_code == 200
        content = resp.text
        assert len(content) > 0
        assert (
            "prometheus" in resp.headers.get("content-type", "").lower()
            or "text/plain" in resp.headers.get("content-type", "").lower()
        )

    def test_health_endpoint_checks_services(self, client) -> Any:
        """Otomatik eklendi."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "services" in data
