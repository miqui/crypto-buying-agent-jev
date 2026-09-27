"""OpenTelemetry setup — traces and metrics.

If OTEL_EXPORTER_OTLP_ENDPOINT is set, spans and metrics are exported via
OTLP HTTP.  Otherwise a console (stdout) exporter is used so there is always
observable output without requiring a collector.
"""
from __future__ import annotations

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_INSTRUMENTATION_NAME = "crypto-buying-agent"


def configure_telemetry(service_name: str, otlp_endpoint: str = "") -> None:
    resource = Resource.create({"service.name": service_name})

    # ── Tracer ────────────────────────────────────────────────────────────────
    tracer_provider = TracerProvider(resource=resource)
    if otlp_endpoint:
        span_exporter: object = OTLPSpanExporter(
            endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces"
        )
    else:
        span_exporter = ConsoleSpanExporter()
    tracer_provider.add_span_processor(
        BatchSpanProcessor(span_exporter)  # type: ignore[arg-type]
    )
    trace.set_tracer_provider(tracer_provider)

    # ── Meter ─────────────────────────────────────────────────────────────────
    if otlp_endpoint:
        metric_exporter: object = OTLPMetricExporter(
            endpoint=f"{otlp_endpoint.rstrip('/')}/v1/metrics"
        )
    else:
        metric_exporter = ConsoleMetricExporter()
    reader = PeriodicExportingMetricReader(
        metric_exporter,  # type: ignore[arg-type]
        export_interval_millis=60_000,
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(_INSTRUMENTATION_NAME)


def get_meter() -> metrics.Meter:
    return metrics.get_meter(_INSTRUMENTATION_NAME)
