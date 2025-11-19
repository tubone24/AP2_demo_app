"""
Tests for Telemetry Module

Tests cover:
- is_telemetry_enabled (environment variable check)
- setup_telemetry (tracer provider setup)
- instrument_fastapi_app (FastAPI instrumentation)
- create_http_span (HTTP span creation)
- get_tracer (tracer retrieval)
- _mask_sensitive_data (sensitive information masking)
- _truncate_body (body truncation)
- _add_request_response_to_span (middleware)
- SENSITIVE_KEYS validation
- MAX_BODY_SIZE constant
"""

import pytest
import os
import json
import unittest.mock
from unittest.mock import Mock, MagicMock, AsyncMock, patch, call


class TestTelemetryEnabled:
    """Test is_telemetry_enabled function"""

    def test_telemetry_disabled_by_default(self, monkeypatch):
        """Test that telemetry is disabled by default"""
        from common.telemetry import is_telemetry_enabled

        # Clear environment variable
        monkeypatch.delenv('OTEL_ENABLED', raising=False)

        # Should be disabled by default
        assert is_telemetry_enabled() is False

    def test_telemetry_enabled_true(self, monkeypatch):
        """Test telemetry enabled with OTEL_ENABLED=true"""
        from common.telemetry import is_telemetry_enabled

        monkeypatch.setenv('OTEL_ENABLED', 'true')

        assert is_telemetry_enabled() is True

    def test_telemetry_enabled_1(self, monkeypatch):
        """Test telemetry enabled with OTEL_ENABLED=1"""
        from common.telemetry import is_telemetry_enabled

        monkeypatch.setenv('OTEL_ENABLED', '1')

        assert is_telemetry_enabled() is True

    def test_telemetry_enabled_yes(self, monkeypatch):
        """Test telemetry enabled with OTEL_ENABLED=yes"""
        from common.telemetry import is_telemetry_enabled

        monkeypatch.setenv('OTEL_ENABLED', 'yes')

        assert is_telemetry_enabled() is True

    def test_telemetry_disabled_false(self, monkeypatch):
        """Test telemetry disabled with OTEL_ENABLED=false"""
        from common.telemetry import is_telemetry_enabled

        monkeypatch.setenv('OTEL_ENABLED', 'false')

        assert is_telemetry_enabled() is False

    def test_telemetry_disabled_0(self, monkeypatch):
        """Test telemetry disabled with OTEL_ENABLED=0"""
        from common.telemetry import is_telemetry_enabled

        monkeypatch.setenv('OTEL_ENABLED', '0')

        assert is_telemetry_enabled() is False


class TestMaskSensitiveData:
    """Test _mask_sensitive_data function"""

    def test_mask_password_in_dict(self):
        """Test that password is masked in dictionary"""
        from common.telemetry import _mask_sensitive_data

        data = {
            'username': 'test_user',
            'password': 'secret123'
        }

        masked = _mask_sensitive_data(data)

        # Verify password is masked
        assert masked['username'] == 'test_user'
        assert masked['password'] == '[REDACTED]'

    def test_mask_token_in_dict(self):
        """Test that token is masked in dictionary"""
        from common.telemetry import _mask_sensitive_data

        data = {
            'user_id': 'user_001',
            'access_token': 'token_abc123'
        }

        masked = _mask_sensitive_data(data)

        # Verify token is masked
        assert masked['user_id'] == 'user_001'
        assert masked['access_token'] == '[REDACTED]'

    def test_mask_api_key_in_dict(self):
        """Test that api_key is masked in dictionary"""
        from common.telemetry import _mask_sensitive_data

        data = {
            'service': 'test',
            'api_key': 'key_xyz789'
        }

        masked = _mask_sensitive_data(data)

        # Verify api_key is masked
        assert masked['service'] == 'test'
        assert masked['api_key'] == '[REDACTED]'

    def test_mask_nested_dict(self):
        """Test that nested dictionary is properly masked"""
        from common.telemetry import _mask_sensitive_data

        data = {
            'user': {
                'name': 'John',
                'password': 'secret'
            }
        }

        masked = _mask_sensitive_data(data)

        # Verify nested password is masked
        assert masked['user']['name'] == 'John'
        assert masked['user']['password'] == '[REDACTED]'

    def test_mask_list_of_dicts(self):
        """Test that list of dictionaries is properly masked"""
        from common.telemetry import _mask_sensitive_data

        data = [
            {'username': 'user1', 'password': 'pass1'},
            {'username': 'user2', 'password': 'pass2'}
        ]

        masked = _mask_sensitive_data(data)

        # Verify all passwords are masked
        assert masked[0]['username'] == 'user1'
        assert masked[0]['password'] == '[REDACTED]'
        assert masked[1]['username'] == 'user2'
        assert masked[1]['password'] == '[REDACTED]'

    def test_mask_secret_in_dict(self):
        """Test that secret is masked in dictionary"""
        from common.telemetry import _mask_sensitive_data

        data = {
            'app_name': 'test_app',
            'client_secret': 'secret_value'
        }

        masked = _mask_sensitive_data(data)

        # Verify secret is masked
        assert masked['app_name'] == 'test_app'
        assert masked['client_secret'] == '[REDACTED]'

    def test_mask_max_depth(self):
        """Test that maximum depth is respected"""
        from common.telemetry import _mask_sensitive_data

        # Create deeply nested structure
        data = {'level1': {'level2': {'level3': {'level4': {'level5': 'value'}}}}}

        # With max_depth=2, should stop at level 2
        masked = _mask_sensitive_data(data, max_depth=2)

        # Verify depth limiting
        assert isinstance(masked, dict)


class TestTruncateBody:
    """Test _truncate_body function"""

    def test_truncate_small_body(self):
        """Test that small body is not truncated"""
        from common.telemetry import _truncate_body

        body = "Short message"
        truncated = _truncate_body(body, max_size=100)

        # Should not be truncated
        assert truncated == body

    def test_truncate_large_body(self):
        """Test that large body is truncated"""
        from common.telemetry import _truncate_body

        body = "A" * 200
        truncated = _truncate_body(body, max_size=100)

        # Should be truncated
        assert len(truncated) > 100
        assert "[TRUNCATED" in truncated
        assert "100 bytes]" in truncated

    def test_truncate_exact_size(self):
        """Test body at exact max size"""
        from common.telemetry import _truncate_body

        body = "A" * 100
        truncated = _truncate_body(body, max_size=100)

        # Should not be truncated at exact size
        assert truncated == body


class TestSensitiveKeys:
    """Test SENSITIVE_KEYS constant"""

    def test_sensitive_keys_defined(self):
        """Test that SENSITIVE_KEYS contains expected keys"""
        from common.telemetry import SENSITIVE_KEYS

        # Verify key sensitive keys are present
        assert 'password' in SENSITIVE_KEYS
        assert 'token' in SENSITIVE_KEYS
        assert 'secret' in SENSITIVE_KEYS
        assert 'api_key' in SENSITIVE_KEYS
        assert 'private_key' in SENSITIVE_KEYS
        assert 'access_token' in SENSITIVE_KEYS
        assert 'authorization' in SENSITIVE_KEYS

    def test_sensitive_keys_is_set(self):
        """Test that SENSITIVE_KEYS is a set"""
        from common.telemetry import SENSITIVE_KEYS

        # Should be a set for efficient lookup
        assert isinstance(SENSITIVE_KEYS, set)


class TestMaxBodySize:
    """Test MAX_BODY_SIZE constant"""

    def test_max_body_size_defined(self):
        """Test that MAX_BODY_SIZE is defined"""
        from common.telemetry import MAX_BODY_SIZE

        # Should be 10KB
        assert MAX_BODY_SIZE == 10000


class TestGetTracer:
    """Test get_tracer function"""

    def test_get_tracer(self):
        """Test get_tracer returns a tracer"""
        from common.telemetry import get_tracer

        tracer = get_tracer('test_module')

        # Verify tracer is returned
        assert tracer is not None


class TestCaseInsensitiveMasking:
    """Test that sensitive keys are matched case-insensitively"""

    def test_mask_uppercase_password(self):
        """Test that PASSWORD (uppercase) is masked"""
        from common.telemetry import _mask_sensitive_data

        data = {'PASSWORD': 'secret123', 'username': 'test'}
        masked = _mask_sensitive_data(data)

        # Should mask PASSWORD (case-insensitive)
        assert masked['PASSWORD'] == '[REDACTED]'
        assert masked['username'] == 'test'

    def test_mask_mixed_case_token(self):
        """Test that Token (mixed case) is masked"""
        from common.telemetry import _mask_sensitive_data

        data = {'Access_Token': 'abc123', 'user_id': '001'}
        masked = _mask_sensitive_data(data)

        # Should mask Access_Token (case-insensitive)
        assert masked['Access_Token'] == '[REDACTED]'
        assert masked['user_id'] == '001'

    def test_mask_partial_match(self):
        """Test that partial matches are detected"""
        from common.telemetry import _mask_sensitive_data

        data = {'user_password': 'secret', 'email': 'test@example.com'}
        masked = _mask_sensitive_data(data)

        # Should mask user_password (contains 'password')
        assert masked['user_password'] == '[REDACTED]'
        assert masked['email'] == 'test@example.com'


class TestNonDictData:
    """Test _mask_sensitive_data with non-dict data"""

    def test_mask_string(self):
        """Test that string values are returned as-is"""
        from common.telemetry import _mask_sensitive_data

        data = "just a string"
        masked = _mask_sensitive_data(data)

        # String should be returned unchanged
        assert masked == data

    def test_mask_number(self):
        """Test that number values are returned as-is"""
        from common.telemetry import _mask_sensitive_data

        data = 12345
        masked = _mask_sensitive_data(data)

        # Number should be returned unchanged
        assert masked == data

    def test_mask_none(self):
        """Test that None values are returned as-is"""
        from common.telemetry import _mask_sensitive_data

        data = None
        masked = _mask_sensitive_data(data)

        # None should be returned unchanged
        assert masked is None


class TestSetupTelemetry:
    """Test setup_telemetry function"""

    def test_setup_telemetry_disabled(self, monkeypatch):
        """Test setup_telemetry when OTEL_ENABLED=false"""
        from common.telemetry import setup_telemetry

        monkeypatch.setenv('OTEL_ENABLED', 'false')

        provider = setup_telemetry()

        # Should return None when disabled
        assert provider is None

    def test_setup_telemetry_enabled_new_provider(self, monkeypatch):
        """Test setup_telemetry creates new provider when enabled"""
        from common.telemetry import setup_telemetry
        from opentelemetry import trace

        monkeypatch.setenv('OTEL_ENABLED', 'true')
        monkeypatch.setenv('OTEL_SERVICE_NAME', 'test_service')
        monkeypatch.setenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://localhost:4317')
        monkeypatch.setenv('OTEL_EXPORTER_OTLP_INSECURE', 'true')

        # Mock OpenTelemetry components
        with patch('common.telemetry.trace.get_tracer_provider') as mock_get_provider, \
             patch('common.telemetry.TracerProvider') as mock_tracer_provider_class, \
             patch('common.telemetry.OTLPSpanExporter') as mock_exporter_class, \
             patch('common.telemetry.BatchSpanProcessor') as mock_processor_class, \
             patch('common.telemetry.trace.set_tracer_provider') as mock_set_provider, \
             patch('common.telemetry.Resource') as mock_resource_class:

            # Mock get_tracer_provider to return ProxyTracerProvider (uninitialized state)
            mock_existing = MagicMock()
            mock_existing.__class__ = trace.ProxyTracerProvider
            mock_get_provider.return_value = mock_existing

            # Mock TracerProvider instance
            mock_provider = MagicMock()
            mock_tracer_provider_class.return_value = mock_provider

            # Mock OTLPSpanExporter
            mock_exporter = MagicMock()
            mock_exporter_class.return_value = mock_exporter

            # Mock BatchSpanProcessor
            mock_processor = MagicMock()
            mock_processor_class.return_value = mock_processor

            # Mock Resource
            mock_resource = MagicMock()
            mock_resource_class.return_value = mock_resource

            provider = setup_telemetry()

            # Should create and return new provider
            assert provider == mock_provider
            mock_tracer_provider_class.assert_called_once_with(resource=mock_resource)
            mock_exporter_class.assert_called_once_with(
                endpoint='http://localhost:4317',
                insecure=True
            )
            mock_provider.add_span_processor.assert_called_once_with(mock_processor)
            mock_set_provider.assert_called_once_with(mock_provider)

    def test_setup_telemetry_custom_service_name(self, monkeypatch):
        """Test setup_telemetry with custom service name"""
        from common.telemetry import setup_telemetry
        from opentelemetry import trace

        monkeypatch.setenv('OTEL_ENABLED', 'true')

        with patch('common.telemetry.trace.get_tracer_provider') as mock_get_provider, \
             patch('common.telemetry.TracerProvider') as mock_tracer_provider_class, \
             patch('common.telemetry.OTLPSpanExporter'), \
             patch('common.telemetry.BatchSpanProcessor'), \
             patch('common.telemetry.trace.set_tracer_provider'), \
             patch('common.telemetry.Resource') as mock_resource_class, \
             patch('common.telemetry.SERVICE_NAME', 'service.name'):

            mock_existing = MagicMock()
            mock_existing.__class__ = trace.ProxyTracerProvider
            mock_get_provider.return_value = mock_existing

            mock_provider = MagicMock()
            mock_tracer_provider_class.return_value = mock_provider

            provider = setup_telemetry(service_name='custom_service')

            # Should use custom service name
            mock_resource_class.assert_called_once()
            call_args = mock_resource_class.call_args
            assert 'attributes' in call_args.kwargs
            assert call_args.kwargs['attributes']['service.name'] == 'custom_service'

    def test_setup_telemetry_existing_provider(self, monkeypatch):
        """Test setup_telemetry with existing TracerProvider"""
        from common.telemetry import setup_telemetry
        from opentelemetry.sdk.trace import TracerProvider

        monkeypatch.setenv('OTEL_ENABLED', 'true')

        with patch('common.telemetry.trace.get_tracer_provider') as mock_get_provider, \
             patch('common.telemetry.OTLPSpanExporter') as mock_exporter_class, \
             patch('common.telemetry.BatchSpanProcessor') as mock_processor_class:

            # Mock existing provider (not NoOp or Proxy) - use real TracerProvider class
            mock_existing = MagicMock()
            mock_existing.__class__ = TracerProvider
            mock_existing.resource = MagicMock()
            mock_existing.resource.attributes = {'service.name': 'existing_service'}
            mock_get_provider.return_value = mock_existing

            # Mock exporter and processor
            mock_exporter = MagicMock()
            mock_exporter_class.return_value = mock_exporter
            mock_processor = MagicMock()
            mock_processor_class.return_value = mock_processor

            provider = setup_telemetry()

            # Should return existing provider and add OTLP exporter
            assert provider == mock_existing
            mock_existing.add_span_processor.assert_called_once_with(mock_processor)

    def test_setup_telemetry_exception_handling(self, monkeypatch):
        """Test setup_telemetry handles exceptions gracefully"""
        from common.telemetry import setup_telemetry

        monkeypatch.setenv('OTEL_ENABLED', 'true')

        with patch('common.telemetry.trace.get_tracer_provider', side_effect=Exception("Test error")):
            provider = setup_telemetry()

            # Should return None on exception
            assert provider is None

    def test_setup_telemetry_insecure_false(self, monkeypatch):
        """Test setup_telemetry with OTEL_EXPORTER_OTLP_INSECURE=false"""
        from common.telemetry import setup_telemetry
        from opentelemetry import trace

        monkeypatch.setenv('OTEL_ENABLED', 'true')
        monkeypatch.setenv('OTEL_EXPORTER_OTLP_INSECURE', 'false')

        with patch('common.telemetry.trace.get_tracer_provider') as mock_get_provider, \
             patch('common.telemetry.TracerProvider') as mock_tracer_provider_class, \
             patch('common.telemetry.OTLPSpanExporter') as mock_exporter_class, \
             patch('common.telemetry.BatchSpanProcessor'), \
             patch('common.telemetry.trace.set_tracer_provider'), \
             patch('common.telemetry.Resource'):

            mock_existing = MagicMock()
            mock_existing.__class__ = trace.ProxyTracerProvider
            mock_get_provider.return_value = mock_existing
            mock_provider = MagicMock()
            mock_tracer_provider_class.return_value = mock_provider

            setup_telemetry()

            # Should pass insecure=False
            mock_exporter_class.assert_called_once()
            call_kwargs = mock_exporter_class.call_args.kwargs
            assert call_kwargs['insecure'] is False

    def test_setup_telemetry_existing_provider_no_resource(self, monkeypatch):
        """Test setup_telemetry with existing provider without resource attribute"""
        from common.telemetry import setup_telemetry
        from opentelemetry.sdk.trace import TracerProvider

        monkeypatch.setenv('OTEL_ENABLED', 'true')

        with patch('common.telemetry.trace.get_tracer_provider') as mock_get_provider, \
             patch('common.telemetry.OTLPSpanExporter') as mock_exporter_class, \
             patch('common.telemetry.BatchSpanProcessor') as mock_processor_class:

            # Mock existing provider without resource attribute
            mock_existing = MagicMock()
            mock_existing.__class__ = TracerProvider
            # Remove resource attribute
            if hasattr(mock_existing, 'resource'):
                delattr(mock_existing, 'resource')
            mock_get_provider.return_value = mock_existing

            # Mock exporter and processor
            mock_exporter = MagicMock()
            mock_exporter_class.return_value = mock_exporter
            mock_processor = MagicMock()
            mock_processor_class.return_value = mock_processor

            provider = setup_telemetry()

            # Should return existing provider and add OTLP exporter
            assert provider == mock_existing
            mock_existing.add_span_processor.assert_called_once_with(mock_processor)

    def test_setup_telemetry_existing_provider_exporter_fails(self, monkeypatch):
        """Test setup_telemetry when adding OTLP exporter to existing provider fails"""
        from common.telemetry import setup_telemetry
        from opentelemetry.sdk.trace import TracerProvider

        monkeypatch.setenv('OTEL_ENABLED', 'true')

        with patch('common.telemetry.trace.get_tracer_provider') as mock_get_provider, \
             patch('common.telemetry.OTLPSpanExporter') as mock_exporter_class, \
             patch('common.telemetry.BatchSpanProcessor') as mock_processor_class:

            # Mock existing provider with resource
            mock_existing = MagicMock()
            mock_existing.__class__ = TracerProvider
            mock_existing.resource = MagicMock()
            mock_existing.resource.attributes = {'service.name': 'existing_service'}

            # Make add_span_processor raise an exception
            mock_existing.add_span_processor.side_effect = Exception("Failed to add processor")
            mock_get_provider.return_value = mock_existing

            # Mock exporter and processor
            mock_exporter = MagicMock()
            mock_exporter_class.return_value = mock_exporter
            mock_processor = MagicMock()
            mock_processor_class.return_value = mock_processor

            provider = setup_telemetry()

            # Should still return existing provider despite error
            assert provider == mock_existing


class TestInstrumentFastAPIApp:
    """Test instrument_fastapi_app function"""

    def test_instrument_fastapi_disabled(self, monkeypatch):
        """Test instrument_fastapi_app when telemetry is disabled"""
        from common.telemetry import instrument_fastapi_app

        monkeypatch.setenv('OTEL_ENABLED', 'false')

        mock_app = MagicMock()

        with patch('common.telemetry.FastAPIInstrumentor') as mock_instrumentor:
            instrument_fastapi_app(mock_app)

            # Should not instrument when disabled
            mock_instrumentor.instrument_app.assert_not_called()

    def test_instrument_fastapi_enabled(self, monkeypatch):
        """Test instrument_fastapi_app when telemetry is enabled"""
        from common.telemetry import instrument_fastapi_app

        monkeypatch.setenv('OTEL_ENABLED', 'true')

        mock_app = MagicMock()
        # Remove the _is_instrumented_by_opentelemetry attribute so hasattr returns False
        if hasattr(mock_app, '_is_instrumented_by_opentelemetry'):
            delattr(mock_app, '_is_instrumented_by_opentelemetry')

        with patch('common.telemetry.FastAPIInstrumentor') as mock_instrumentor_class:
            mock_instrumentor = MagicMock()
            mock_instrumentor_class.return_value = mock_instrumentor
            mock_instrumentor_class.instrument_app = MagicMock()

            instrument_fastapi_app(mock_app)

            # Should instrument app
            mock_instrumentor_class.instrument_app.assert_called_once_with(mock_app)
            mock_app.add_middleware.assert_called_once()
            assert mock_app._is_instrumented_by_opentelemetry is True

    def test_instrument_fastapi_already_instrumented(self, monkeypatch):
        """Test instrument_fastapi_app with already instrumented app"""
        from common.telemetry import instrument_fastapi_app

        monkeypatch.setenv('OTEL_ENABLED', 'true')

        mock_app = MagicMock()
        mock_app._is_instrumented_by_opentelemetry = True

        with patch('common.telemetry.FastAPIInstrumentor') as mock_instrumentor:
            instrument_fastapi_app(mock_app)

            # Should skip instrumentation
            mock_instrumentor.instrument_app.assert_not_called()
            mock_app.add_middleware.assert_not_called()

    def test_instrument_fastapi_exception_handling(self, monkeypatch):
        """Test instrument_fastapi_app handles exceptions"""
        from common.telemetry import instrument_fastapi_app

        monkeypatch.setenv('OTEL_ENABLED', 'true')

        mock_app = MagicMock()

        with patch('common.telemetry.FastAPIInstrumentor.instrument_app', side_effect=Exception("Test error")):
            # Should not raise exception
            instrument_fastapi_app(mock_app)

    def test_instrument_fastapi_middleware_exception(self, monkeypatch):
        """Test instrument_fastapi_app handles middleware addition exceptions"""
        from common.telemetry import instrument_fastapi_app

        monkeypatch.setenv('OTEL_ENABLED', 'true')

        mock_app = MagicMock()
        # Make add_middleware raise an exception
        mock_app.add_middleware.side_effect = Exception("Middleware error")

        with patch('common.telemetry.FastAPIInstrumentor.instrument_app'):
            # Should not raise exception
            instrument_fastapi_app(mock_app)


class TestCreateHTTPSpan:
    """Test create_http_span function"""

    def test_create_http_span_basic(self):
        """Test create_http_span creates span with basic attributes"""
        from common.telemetry import create_http_span

        mock_tracer = MagicMock()
        mock_span = MagicMock()

        # Mock the context manager
        mock_context_manager = MagicMock()
        mock_context_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_context_manager.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_context_manager

        with create_http_span(mock_tracer, "POST", "http://example.com/api") as span:
            assert span == mock_span

        # Verify span attributes were set
        assert mock_span.set_attribute.call_count >= 2
        mock_span.set_attribute.assert_any_call("http.method", "POST")
        mock_span.set_attribute.assert_any_call("http.url", "http://example.com/api")

    def test_create_http_span_with_custom_attributes(self):
        """Test create_http_span with custom attributes"""
        from common.telemetry import create_http_span

        mock_tracer = MagicMock()
        mock_span = MagicMock()

        mock_context_manager = MagicMock()
        mock_context_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_context_manager.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_context_manager

        with create_http_span(
            mock_tracer,
            "GET",
            "http://example.com",
            message_type="ap2/IntentMandate",
            custom_attr="custom_value"
        ) as span:
            assert span == mock_span

        # Verify custom attributes were set
        mock_span.set_attribute.assert_any_call("message_type", "ap2/IntentMandate")
        mock_span.set_attribute.assert_any_call("custom_attr", "custom_value")

    def test_create_http_span_kind(self):
        """Test create_http_span sets correct span kind"""
        from common.telemetry import create_http_span
        import common.telemetry as telemetry_module

        mock_tracer = MagicMock()
        mock_span = MagicMock()

        mock_context_manager = MagicMock()
        mock_context_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_context_manager.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_context_manager

        with patch.object(telemetry_module.trace, 'SpanKind') as mock_span_kind:
            mock_span_kind.CLIENT = 'CLIENT'

            with create_http_span(mock_tracer, "POST", "http://example.com"):
                pass

            # Verify span was created with CLIENT kind
            mock_tracer.start_as_current_span.assert_called_once()
            call_args = mock_tracer.start_as_current_span.call_args
            assert call_args.kwargs.get('kind') == 'CLIENT'


class TestAddRequestResponseToSpan:
    """Test _add_request_response_to_span middleware"""

    @pytest.mark.asyncio
    async def test_middleware_no_span(self):
        """Test middleware when no span is recording"""
        from common.telemetry import _add_request_response_to_span

        mock_request = MagicMock()
        mock_response = MagicMock()

        async def mock_call_next(request):
            return mock_response

        with patch('common.telemetry.trace.get_current_span') as mock_get_span:
            # Mock span that is not recording
            mock_span = MagicMock()
            mock_span.is_recording.return_value = False
            mock_get_span.return_value = mock_span

            response = await _add_request_response_to_span(mock_request, mock_call_next)

            # Should return response without processing
            assert response == mock_response
            mock_span.set_attribute.assert_not_called()

    @pytest.mark.asyncio
    async def test_middleware_json_request_body(self):
        """Test middleware with JSON request body"""
        from common.telemetry import _add_request_response_to_span

        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.headers = {"content-type": "application/json"}

        request_body = {"username": "test_user", "password": "secret123"}
        mock_request.body = AsyncMock(return_value=json.dumps(request_body).encode('utf-8'))

        mock_response = MagicMock()

        async def mock_call_next(request):
            return mock_response

        with patch('common.telemetry.trace.get_current_span') as mock_get_span:
            mock_span = MagicMock()
            mock_span.is_recording.return_value = True
            mock_get_span.return_value = mock_span

            response = await _add_request_response_to_span(mock_request, mock_call_next)

            # Verify request body was masked and added to span
            mock_span.set_attribute.assert_any_call("http.request.body", unittest.mock.ANY)

            # Find the call with http.request.body
            for call in mock_span.set_attribute.call_args_list:
                if call[0][0] == "http.request.body":
                    body_value = json.loads(call[0][1])
                    # Password should be masked
                    assert body_value['password'] == '[REDACTED]'
                    assert body_value['username'] == 'test_user'

    @pytest.mark.asyncio
    async def test_middleware_response_duration(self):
        """Test middleware records response duration"""
        from common.telemetry import _add_request_response_to_span

        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.headers = {}

        mock_response = MagicMock()

        async def mock_call_next(request):
            return mock_response

        with patch('common.telemetry.trace.get_current_span') as mock_get_span:
            mock_span = MagicMock()
            mock_span.is_recording.return_value = True
            mock_get_span.return_value = mock_span

            response = await _add_request_response_to_span(mock_request, mock_call_next)

            # Verify duration was recorded
            duration_calls = [call for call in mock_span.set_attribute.call_args_list
                             if call[0][0] == "http.response.duration_ms"]
            assert len(duration_calls) > 0

    @pytest.mark.asyncio
    async def test_middleware_exception_handling(self):
        """Test middleware handles exceptions"""
        from common.telemetry import _add_request_response_to_span

        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.headers = {}

        test_exception = Exception("Test error")

        async def mock_call_next(request):
            raise test_exception

        with patch('common.telemetry.trace.get_current_span') as mock_get_span, \
             patch('common.telemetry.trace.Status') as mock_status, \
             patch('common.telemetry.trace.StatusCode') as mock_status_code:

            mock_span = MagicMock()
            mock_span.is_recording.return_value = True
            mock_get_span.return_value = mock_span

            mock_status_code.ERROR = 'ERROR'

            with pytest.raises(Exception) as exc_info:
                await _add_request_response_to_span(mock_request, mock_call_next)

            # Verify exception was recorded
            mock_span.record_exception.assert_called_once_with(test_exception)
            assert exc_info.value == test_exception

    @pytest.mark.asyncio
    async def test_middleware_request_body_parse_error(self):
        """Test middleware handles request body parse errors"""
        from common.telemetry import _add_request_response_to_span

        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.headers = {"content-type": "application/json"}
        # Invalid JSON
        mock_request.body = AsyncMock(return_value=b"{invalid json")

        mock_response = MagicMock()

        async def mock_call_next(request):
            return mock_response

        with patch('common.telemetry.trace.get_current_span') as mock_get_span:
            mock_span = MagicMock()
            mock_span.is_recording.return_value = True
            mock_get_span.return_value = mock_span

            response = await _add_request_response_to_span(mock_request, mock_call_next)

            # Should still return response despite parse error
            assert response == mock_response

            # Verify error was recorded in span
            error_calls = [call for call in mock_span.set_attribute.call_args_list
                          if call[0][0] == "http.request.body.error"]
            assert len(error_calls) > 0

    @pytest.mark.asyncio
    async def test_middleware_json_response_body(self):
        """Test middleware with JSON response body"""
        from common.telemetry import _add_request_response_to_span

        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.headers = {}

        response_body = {"status": "success", "password": "secret123"}
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "application/json"}
        mock_response.body = json.dumps(response_body).encode('utf-8')

        async def mock_call_next(request):
            return mock_response

        with patch('common.telemetry.trace.get_current_span') as mock_get_span:
            mock_span = MagicMock()
            mock_span.is_recording.return_value = True
            mock_get_span.return_value = mock_span

            response = await _add_request_response_to_span(mock_request, mock_call_next)

            # Verify response body was masked and added to span
            response_body_calls = [call for call in mock_span.set_attribute.call_args_list
                                  if call[0][0] == "http.response.body"]
            assert len(response_body_calls) > 0

            # Find the call with http.response.body
            for call in mock_span.set_attribute.call_args_list:
                if call[0][0] == "http.response.body":
                    body_value = json.loads(call[0][1])
                    # Password should be masked
                    assert body_value['password'] == '[REDACTED]'
                    assert body_value['status'] == 'success'

    @pytest.mark.asyncio
    async def test_middleware_response_body_parse_error(self):
        """Test middleware handles response body parse errors"""
        from common.telemetry import _add_request_response_to_span

        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.headers = {}

        mock_response = MagicMock()
        mock_response.headers = {"content-type": "application/json"}
        # Invalid JSON
        mock_response.body = b"{invalid json"

        async def mock_call_next(request):
            return mock_response

        with patch('common.telemetry.trace.get_current_span') as mock_get_span:
            mock_span = MagicMock()
            mock_span.is_recording.return_value = True
            mock_get_span.return_value = mock_span

            response = await _add_request_response_to_span(mock_request, mock_call_next)

            # Should still return response despite parse error
            assert response == mock_response

            # Verify error was recorded in span
            error_calls = [call for call in mock_span.set_attribute.call_args_list
                          if call[0][0] == "http.response.body.error"]
            assert len(error_calls) > 0

    @pytest.mark.asyncio
    async def test_middleware_request_body_can_be_reread(self):
        """Test middleware allows request body to be re-read"""
        from common.telemetry import _add_request_response_to_span

        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.headers = {"content-type": "application/json"}

        request_body = {"username": "test_user", "data": "test_data"}
        body_bytes = json.dumps(request_body).encode('utf-8')
        mock_request.body = AsyncMock(return_value=body_bytes)

        mock_response = MagicMock()

        # Track if _receive was set
        receive_was_set = False

        async def mock_call_next(request):
            nonlocal receive_was_set
            # Check if _receive attribute was set and can be called
            if hasattr(request, '_receive'):
                receive_was_set = True
                # Call the receive function to test line 241
                result = await request._receive()
                # Verify the receive function returns the expected format
                assert result["type"] == "http.request"
                assert result["body"] == body_bytes
            return mock_response

        with patch('common.telemetry.trace.get_current_span') as mock_get_span:
            mock_span = MagicMock()
            mock_span.is_recording.return_value = True
            mock_get_span.return_value = mock_span

            response = await _add_request_response_to_span(mock_request, mock_call_next)

            # Verify response was returned
            assert response == mock_response
            # Verify _receive was set and tested
            assert receive_was_set
