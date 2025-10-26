"""
v2/common/telemetry.py

OpenTelemetry分散トレーシング設定モジュール

A2A通信の分散トレーシングを実現するため、
FastAPIとhttpxクライアントにOpenTelemetryを統合

参考: https://zenn.dev/kimitsu/articles/otel-and-a2a
"""

import os
import logging
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

logger = logging.getLogger(__name__)


def is_telemetry_enabled() -> bool:
    """
    OpenTelemetryが有効かどうかを環境変数から判定

    Returns:
        bool: OTEL_ENABLEDがtrue/1の場合はTrue
    """
    otel_enabled = os.getenv("OTEL_ENABLED", "false").lower()
    return otel_enabled in ("true", "1", "yes")


def setup_telemetry(service_name: Optional[str] = None) -> Optional[TracerProvider]:
    """
    OpenTelemetry分散トレーシングのセットアップ

    環境変数:
        OTEL_ENABLED: トレーシング有効/無効（デフォルト: false）
        OTEL_SERVICE_NAME: サービス名（デフォルト: unknown_service）
        OTEL_EXPORTER_OTLP_ENDPOINT: OTLPエンドポイント（デフォルト: http://jaeger:4317）
        OTEL_EXPORTER_OTLP_INSECURE: 非セキュア接続（デフォルト: true）

    Args:
        service_name: サービス名（指定しない場合は環境変数から取得）

    Returns:
        Optional[TracerProvider]: トレーサープロバイダー（無効時はNone）
    """
    # トレーシング無効の場合は何もしない
    if not is_telemetry_enabled():
        logger.info("[Telemetry] OpenTelemetry is disabled (OTEL_ENABLED=false)")
        return None

    try:
        # 既にTracerProviderが設定されているかチェック
        existing_provider = trace.get_tracer_provider()
        provider_type = type(existing_provider).__name__
        logger.info(f"[Telemetry] Current TracerProvider type: {provider_type}")

        # NoOpTracerProvider, ProxyTracerProviderでない場合は、既に設定済み
        # ProxyTracerProviderは未初期化状態なので設定が必要
        if not isinstance(existing_provider, (trace.NoOpTracerProvider, trace.ProxyTracerProvider)):
            # 既存のTracerProviderにOTLPエクスポーターを追加
            if hasattr(existing_provider, 'resource'):
                existing_service_name = existing_provider.resource.attributes.get(SERVICE_NAME, "unknown")
                logger.info(
                    f"[Telemetry] TracerProvider already exists ({provider_type}) "
                    f"with service_name='{existing_service_name}'. "
                    f"Adding OTLP exporter to existing provider."
                )
            else:
                logger.info(
                    f"[Telemetry] TracerProvider already exists ({provider_type}). "
                    f"Adding OTLP exporter to existing provider."
                )

            # OTLPエクスポーター設定
            otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
            otlp_insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() in ("true", "1", "yes")

            # 既存のプロバイダーにOTLPエクスポーターを追加
            try:
                otlp_exporter = OTLPSpanExporter(
                    endpoint=otlp_endpoint,
                    insecure=otlp_insecure
                )
                existing_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
                logger.info(f"[Telemetry] OTLP exporter added successfully to existing TracerProvider (endpoint: {otlp_endpoint})")
            except Exception as e:
                logger.error(f"[Telemetry] Failed to add OTLP exporter to existing TracerProvider: {e}")

            return existing_provider

        # サービス名の取得
        if service_name is None:
            service_name = os.getenv("OTEL_SERVICE_NAME", "unknown_service")

        # OTLPエクスポーター設定
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
        otlp_insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() in ("true", "1", "yes")

        logger.info(
            f"[Telemetry] Initializing OpenTelemetry:\n"
            f"  Service Name: {service_name}\n"
            f"  OTLP Endpoint: {otlp_endpoint}\n"
            f"  Insecure: {otlp_insecure}"
        )

        # リソース定義（サービス名を含む）
        resource = Resource(attributes={
            SERVICE_NAME: service_name
        })

        # トレーサープロバイダー作成
        provider = TracerProvider(resource=resource)

        # OTLPエクスポーター作成
        otlp_exporter = OTLPSpanExporter(
            endpoint=otlp_endpoint,
            insecure=otlp_insecure
        )

        # バッチスパンプロセッサー追加
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

        # グローバルトレーサープロバイダーを設定
        trace.set_tracer_provider(provider)

        logger.info(f"[Telemetry] OpenTelemetry initialized successfully for service: {service_name}")

        return provider

    except Exception as e:
        logger.error(f"[Telemetry] Failed to initialize OpenTelemetry: {e}", exc_info=True)
        return None


def instrument_fastapi_app(app):
    """
    FastAPIアプリにOpenTelemetry計装を追加

    参考記事によると、FastAPIInstrumentor.instrument_app()を使用してアプリを計装する。
    opentelemetry-bootstrapの自動インストールは避ける（Click依存の問題を回避）。

    Args:
        app: FastAPIアプリインスタンス
    """
    if not is_telemetry_enabled():
        logger.debug("[Telemetry] FastAPI instrumentation skipped (OTEL_ENABLED=false)")
        return

    try:
        # 既に計装済みかチェック（middleware確認）
        if hasattr(app, '_is_instrumented_by_opentelemetry'):
            logger.debug("[Telemetry] FastAPI app already instrumented, skipping")
            return

        # FastAPIアプリを計装
        FastAPIInstrumentor.instrument_app(app)
        app._is_instrumented_by_opentelemetry = True
        logger.info("[Telemetry] FastAPI app instrumented successfully")
    except Exception as e:
        logger.error(f"[Telemetry] Failed to instrument FastAPI app: {e}", exc_info=True)


def create_http_span(tracer: trace.Tracer, method: str, url: str, **attributes):
    """
    HTTP通信用のスパンを作成するヘルパー関数

    手動計装用：A2A通信、MCP通信、エンティティ間通信で使用

    Args:
        tracer: OpenTelemetryトレーサー
        method: HTTPメソッド (GET, POST, etc.)
        url: リクエストURL
        **attributes: 追加のスパン属性

    Returns:
        context manager: スパンのコンテキストマネージャー

    Usage:
        tracer = get_tracer(__name__)
        with create_http_span(tracer, "POST", "http://merchant:8002/a2a/message",
                             message_type="ap2/IntentMandate") as span:
            response = httpx.post(...)
            span.set_attribute("http.status_code", response.status_code)
    """
    # コンテキストマネージャーを作成
    # IMPORTANT: tracer.start_as_current_span()は_AgnosticContextManagerを返す
    # そのため、with文で使用してspanオブジェクトを取得する必要がある
    from contextlib import contextmanager

    @contextmanager
    def http_span_context():
        with tracer.start_as_current_span(
            f"HTTP {method}",
            kind=trace.SpanKind.CLIENT
        ) as span:
            # 標準的なHTTP属性を設定
            span.set_attribute("http.method", method)
            span.set_attribute("http.url", url)

            # 追加属性を設定
            for key, value in attributes.items():
                span.set_attribute(key, value)

            yield span

    return http_span_context()


def get_tracer(name: str) -> trace.Tracer:
    """
    トレーサーを取得

    Args:
        name: トレーサー名（通常はモジュール名）

    Returns:
        trace.Tracer: トレーサーインスタンス
    """
    return trace.get_tracer(name)
