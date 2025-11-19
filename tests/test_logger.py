"""
Tests for Logger Module

Tests cover:
- SensitiveDataFilter (masking sensitive data)
- StructuredFormatter (JSON and text formatting)
- setup_logger (logger configuration)
- HTTP request/response logging
- A2A message logging
- MCP request/response logging
- Crypto operation logging
- Database operation logging
- LoggingAsyncClient (HTTP client wrapper)
"""

import pytest
import logging
import json
import os
import sys
from io import StringIO
from unittest.mock import Mock, MagicMock, AsyncMock, patch


class TestSensitiveDataFilter:
    """Test SensitiveDataFilter for masking sensitive information"""

    def test_filter_masks_password(self):
        """Test that password fields are masked"""
        from common.logger import SensitiveDataFilter

        filter_instance = SensitiveDataFilter()

        # Create a log record with password
        logger = logging.getLogger('test')
        record = logger.makeRecord(
            logger.name, logging.INFO, '', 0, '{"password": "secret123"}', (), None
        )

        # Apply filter
        filter_instance.filter(record)

        # Verify password is masked
        assert '***MASKED***' in record.msg
        assert 'secret123' not in record.msg

    def test_filter_masks_token(self):
        """Test that token fields are masked"""
        from common.logger import SensitiveDataFilter

        filter_instance = SensitiveDataFilter()

        # Create a log record with token
        logger = logging.getLogger('test')
        record = logger.makeRecord(
            logger.name, logging.INFO, '', 0, '{"token": "abc123xyz"}', (), None
        )

        # Apply filter
        filter_instance.filter(record)

        # Verify token is masked
        assert '***MASKED***' in record.msg
        assert 'abc123xyz' not in record.msg

    def test_filter_masks_api_key(self):
        """Test that api_key fields are masked"""
        from common.logger import SensitiveDataFilter

        filter_instance = SensitiveDataFilter()

        # Create a log record with api_key
        logger = logging.getLogger('test')
        record = logger.makeRecord(
            logger.name, logging.INFO, '', 0, '{"api_key": "key_12345"}', (), None
        )

        # Apply filter
        filter_instance.filter(record)

        # Verify api_key is masked
        assert '***MASKED***' in record.msg
        assert 'key_12345' not in record.msg

    def test_filter_preserves_non_sensitive_data(self):
        """Test that non-sensitive data is preserved"""
        from common.logger import SensitiveDataFilter

        filter_instance = SensitiveDataFilter()

        # Create a log record with non-sensitive data
        logger = logging.getLogger('test')
        record = logger.makeRecord(
            logger.name, logging.INFO, '', 0, '{"username": "test_user", "email": "test@example.com"}', (), None
        )

        # Apply filter
        filter_instance.filter(record)

        # Verify non-sensitive data is preserved
        assert 'test_user' in record.msg
        assert 'test@example.com' in record.msg

    def test_filter_already_masked(self):
        """Test that already masked data is not processed again"""
        from common.logger import SensitiveDataFilter

        filter_instance = SensitiveDataFilter()

        # Create a log record with already masked data
        logger = logging.getLogger('test')
        record = logger.makeRecord(
            logger.name, logging.INFO, '', 0, 'Password: ***MASKED***', (), None
        )

        original_msg = record.msg
        filter_instance.filter(record)

        # Verify message is unchanged
        assert record.msg == original_msg


class TestStructuredFormatter:
    """Test StructuredFormatter for log formatting"""

    def test_text_format(self):
        """Test human-readable text format"""
        from common.logger import StructuredFormatter

        formatter = StructuredFormatter(json_format=False)

        logger = logging.getLogger('test')
        record = logger.makeRecord(
            logger.name, logging.INFO, '', 1, 'Test message', (), None
        )

        formatted = formatter.format(record)

        # Verify text format
        assert 'INFO' in formatted
        assert 'test' in formatted
        assert 'Test message' in formatted

    def test_json_format(self):
        """Test JSON format"""
        from common.logger import StructuredFormatter

        formatter = StructuredFormatter(json_format=True)

        logger = logging.getLogger('test')
        record = logger.makeRecord(
            logger.name, logging.INFO, 'test.py', 1, 'Test message', (), None
        )

        formatted = formatter.format(record)

        # Verify JSON format
        log_data = json.loads(formatted)
        assert log_data['level'] == 'INFO'
        assert log_data['logger'] == 'test'
        assert log_data['message'] == 'Test message'
        assert 'timestamp' in log_data

    def test_json_format_with_service_name(self):
        """Test JSON format with service_name attribute"""
        from common.logger import StructuredFormatter

        formatter = StructuredFormatter(json_format=True)

        logger = logging.getLogger('test')
        record = logger.makeRecord(
            logger.name, logging.INFO, 'test.py', 1, 'Test message', (), None
        )
        record.service_name = 'test_service'

        formatted = formatter.format(record)

        # Verify service_name is included
        log_data = json.loads(formatted)
        assert log_data['service'] == 'test_service'


class TestLoggerSetup:
    """Test setup_logger function"""

    def test_setup_logger_default(self):
        """Test basic logger setup"""
        from common.logger import setup_logger

        logger = setup_logger('test_logger_1', level='INFO')

        # Verify logger configuration
        assert logger.name == 'test_logger_1'
        assert logger.level == logging.INFO
        assert len(logger.handlers) > 0

    def test_setup_logger_debug_level(self):
        """Test logger with DEBUG level"""
        from common.logger import setup_logger

        logger = setup_logger('test_logger_2', level='DEBUG')

        # Verify DEBUG level
        assert logger.level == logging.DEBUG

    def test_setup_logger_with_service_name(self):
        """Test logger with service name"""
        from common.logger import setup_logger

        logger = setup_logger('test_logger_3', service_name='test_service')

        # Verify service_name attribute
        assert hasattr(logger, 'service_name')
        assert logger.service_name == 'test_service'

    def test_setup_logger_invalid_level(self):
        """Test logger with invalid log level"""
        from common.logger import setup_logger

        # Should default to INFO for invalid level
        logger = setup_logger('test_logger_4', level='INVALID')

        # Verify defaults to INFO
        assert logger.level == logging.INFO


class TestHTTPLogging:
    """Test HTTP request/response logging functions"""

    def test_log_http_request(self):
        """Test HTTP request logging"""
        from common.logger import setup_logger, log_http_request

        logger = setup_logger('test_http', level='INFO')

        # Should not raise exception
        log_http_request(
            logger=logger,
            method='POST',
            url='http://example.com/api',
            headers={'Content-Type': 'application/json'},
            body={'test': 'data'}
        )

    def test_log_http_response(self):
        """Test HTTP response logging"""
        from common.logger import setup_logger, log_http_response

        logger = setup_logger('test_http_resp', level='INFO')

        # Should not raise exception
        log_http_response(
            logger=logger,
            status_code=200,
            headers={'Content-Type': 'application/json'},
            body={'result': 'success'},
            duration_ms=123.45
        )


class TestA2ALogging:
    """Test A2A message logging"""

    def test_log_a2a_message_sent(self):
        """Test A2A message sent logging"""
        from common.logger import setup_logger, log_a2a_message

        logger = setup_logger('test_a2a', level='INFO')

        # Should not raise exception
        log_a2a_message(
            logger=logger,
            direction='sent',
            message_type='ap2/IntentMandate',
            payload={'mandate': 'data'},
            peer='did:ap2:merchant:test'
        )

    def test_log_a2a_message_received(self):
        """Test A2A message received logging"""
        from common.logger import setup_logger, log_a2a_message

        logger = setup_logger('test_a2a_recv', level='INFO')

        # Should not raise exception
        log_a2a_message(
            logger=logger,
            direction='received',
            message_type='ap2/CartMandate',
            payload={'cart': 'data'},
            peer='did:ap2:agent:shopping'
        )


class TestMCPLogging:
    """Test MCP request/response logging"""

    def test_log_mcp_request(self):
        """Test MCP request logging"""
        from common.logger import setup_logger, log_mcp_request

        logger = setup_logger('test_mcp', level='INFO')

        # Should not raise exception
        log_mcp_request(
            logger=logger,
            tool_name='search_products',
            arguments={'query': 'shoes'},
            url='http://mcp-server:8000'
        )

    def test_log_mcp_response_success(self):
        """Test MCP response logging (success)"""
        from common.logger import setup_logger, log_mcp_response

        logger = setup_logger('test_mcp_resp', level='INFO')

        # Should not raise exception
        log_mcp_response(
            logger=logger,
            tool_name='search_products',
            result={'products': []},
            duration_ms=50.0
        )

    def test_log_mcp_response_error(self):
        """Test MCP response logging (error)"""
        from common.logger import setup_logger, log_mcp_response

        logger = setup_logger('test_mcp_err', level='INFO')

        # Should not raise exception
        log_mcp_response(
            logger=logger,
            tool_name='search_products',
            result=None,
            error='Connection timeout'
        )


class TestCryptoLogging:
    """Test crypto operation logging"""

    def test_log_crypto_sign(self):
        """Test crypto sign operation logging"""
        from common.logger import setup_logger, log_crypto_operation

        logger = setup_logger('test_crypto', level='INFO')

        # Should not raise exception
        log_crypto_operation(
            logger=logger,
            operation='sign',
            algorithm='ecdsa',
            key_id='key-1',
            success=True
        )

    def test_log_crypto_verify_failed(self):
        """Test crypto verify operation logging (failed)"""
        from common.logger import setup_logger, log_crypto_operation

        logger = setup_logger('test_crypto_fail', level='INFO')

        # Should not raise exception
        log_crypto_operation(
            logger=logger,
            operation='verify',
            algorithm='ed25519',
            key_id='key-2',
            success=False
        )


class TestDatabaseLogging:
    """Test database operation logging"""

    def test_log_database_select(self):
        """Test database SELECT logging"""
        from common.logger import setup_logger, log_database_operation

        logger = setup_logger('test_db', level='DEBUG')

        # Should not raise exception
        log_database_operation(
            logger=logger,
            operation='SELECT',
            table='products',
            record_id='SHOE-001',
            duration_ms=5.0
        )

    def test_log_database_insert(self):
        """Test database INSERT logging"""
        from common.logger import setup_logger, log_database_operation

        logger = setup_logger('test_db_insert', level='DEBUG')

        # Should not raise exception
        log_database_operation(
            logger=logger,
            operation='INSERT',
            table='users',
            record_id='user_001',
            duration_ms=10.0
        )


class TestGetLogger:
    """Test get_logger helper function"""

    def test_get_logger(self):
        """Test get_logger helper"""
        from common.logger import get_logger

        logger = get_logger('test_helper')

        # Verify logger is returned
        assert logger is not None
        assert logger.name == 'test_helper'

    def test_get_logger_with_service_name(self):
        """Test get_logger with service name"""
        from common.logger import get_logger

        logger = get_logger('test_helper_svc', service_name='my_service')

        # Verify service_name is set
        assert hasattr(logger, 'service_name')
        assert logger.service_name == 'my_service'


class TestSensitiveKeys:
    """Test that all sensitive keys are properly masked"""

    def test_all_sensitive_keys_masked(self):
        """Test that all SENSITIVE_KEYS are masked"""
        from common.logger import SensitiveDataFilter

        filter_instance = SensitiveDataFilter()
        sensitive_keys = SensitiveDataFilter.SENSITIVE_KEYS

        # Verify all keys are properly identified
        assert 'password' in sensitive_keys
        assert 'token' in sensitive_keys
        assert 'secret' in sensitive_keys
        assert 'api_key' in sensitive_keys
        assert 'private_key' in sensitive_keys

    def test_filter_nested_sensitive_data(self):
        """Test masking nested sensitive data"""
        from common.logger import SensitiveDataFilter

        filter_instance = SensitiveDataFilter()
        logger = logging.getLogger('test')

        nested_data = {
            "user": {
                "username": "john",
                "password": "secret123",
                "profile": {
                    "api_key": "key123"
                }
            }
        }

        record = logger.makeRecord(
            logger.name, logging.INFO, '', 0, json.dumps(nested_data), (), None
        )

        filter_instance.filter(record)

        # Verify nested sensitive data is masked
        assert '***MASKED***' in record.msg
        assert 'secret123' not in record.msg
        assert 'key123' not in record.msg
        # Non-sensitive data should be preserved
        assert 'john' in record.msg

    def test_filter_list_with_sensitive_data(self):
        """Test masking sensitive data in dicts containing lists"""
        from common.logger import SensitiveDataFilter

        filter_instance = SensitiveDataFilter()
        logger = logging.getLogger('test')

        # Note: Filter only handles JSON objects (dicts) starting with '{', not arrays
        # This is by design as mentioned in the filter code
        data_with_list = {
            "users": [
                {"username": "user1", "password": "pass1"},
                {"username": "user2", "token": "token123"}
            ]
        }

        record = logger.makeRecord(
            logger.name, logging.INFO, '', 0, json.dumps(data_with_list), (), None
        )

        filter_instance.filter(record)

        # Verify sensitive data in nested lists is masked
        assert '***MASKED***' in record.msg
        assert 'pass1' not in record.msg
        assert 'token123' not in record.msg

    def test_filter_non_json_message(self):
        """Test that non-JSON messages are handled correctly"""
        from common.logger import SensitiveDataFilter

        filter_instance = SensitiveDataFilter()
        logger = logging.getLogger('test')

        record = logger.makeRecord(
            logger.name, logging.INFO, '', 0, 'This is a plain text message', (), None
        )

        # Should not raise exception
        result = filter_instance.filter(record)

        assert result is True
        assert record.msg == 'This is a plain text message'

    def test_filter_invalid_json(self):
        """Test that invalid JSON is handled gracefully"""
        from common.logger import SensitiveDataFilter

        filter_instance = SensitiveDataFilter()
        logger = logging.getLogger('test')

        record = logger.makeRecord(
            logger.name, logging.INFO, '', 0, '{"invalid": json}', (), None
        )

        # Should not raise exception
        result = filter_instance.filter(record)

        assert result is True


class TestStructuredFormatterExtended:
    """Extended tests for StructuredFormatter"""

    def test_json_format_with_request_id(self):
        """Test JSON format with request_id attribute"""
        from common.logger import StructuredFormatter

        formatter = StructuredFormatter(json_format=True)
        logger = logging.getLogger('test')

        record = logger.makeRecord(
            logger.name, logging.INFO, 'test.py', 1, 'Test message', (), None
        )
        record.request_id = 'req-12345'

        formatted = formatter.format(record)

        log_data = json.loads(formatted)
        assert log_data['request_id'] == 'req-12345'

    def test_json_format_with_user_id(self):
        """Test JSON format with user_id attribute"""
        from common.logger import StructuredFormatter

        formatter = StructuredFormatter(json_format=True)
        logger = logging.getLogger('test')

        record = logger.makeRecord(
            logger.name, logging.INFO, 'test.py', 1, 'Test message', (), None
        )
        record.user_id = 'user-67890'

        formatted = formatter.format(record)

        log_data = json.loads(formatted)
        assert log_data['user_id'] == 'user-67890'

    def test_json_format_with_exception(self):
        """Test JSON format with exception info"""
        from common.logger import StructuredFormatter

        formatter = StructuredFormatter(json_format=True)
        logger = logging.getLogger('test')

        try:
            raise ValueError("Test error")
        except ValueError:
            record = logger.makeRecord(
                logger.name, logging.ERROR, 'test.py', 1, 'Error occurred', (), sys.exc_info()
            )

        formatted = formatter.format(record)

        log_data = json.loads(formatted)
        assert 'exception' in log_data
        assert 'ValueError' in log_data['exception']
        assert 'Test error' in log_data['exception']


class TestLoggerSetupEnvironment:
    """Test setup_logger with environment variables"""

    def test_setup_logger_from_env_debug(self):
        """Test logger setup from LOG_LEVEL environment variable"""
        from common.logger import setup_logger

        with patch.dict(os.environ, {'LOG_LEVEL': 'DEBUG'}):
            logger = setup_logger('test_env_debug', level=None)
            assert logger.level == logging.DEBUG

    def test_setup_logger_from_env_warning(self):
        """Test logger setup with WARNING level from environment"""
        from common.logger import setup_logger

        with patch.dict(os.environ, {'LOG_LEVEL': 'WARNING'}):
            logger = setup_logger('test_env_warning', level=None)
            assert logger.level == logging.WARNING

    def test_setup_logger_json_format_from_env(self):
        """Test logger with JSON format from environment variable"""
        from common.logger import setup_logger

        with patch.dict(os.environ, {'LOG_FORMAT': 'json'}):
            logger = setup_logger('test_json_env')

            # Check that formatter is StructuredFormatter with JSON
            handler = logger.handlers[0]
            from common.logger import StructuredFormatter
            assert isinstance(handler.formatter, StructuredFormatter)
            assert handler.formatter.json_format is True

    def test_setup_logger_text_format_from_env(self):
        """Test logger with text format from environment variable"""
        from common.logger import setup_logger

        with patch.dict(os.environ, {'LOG_FORMAT': 'text'}):
            logger = setup_logger('test_text_env')

            # Check that formatter is StructuredFormatter without JSON
            handler = logger.handlers[0]
            from common.logger import StructuredFormatter
            assert isinstance(handler.formatter, StructuredFormatter)
            assert handler.formatter.json_format is False

    def test_setup_logger_no_duplicate_handlers(self):
        """Test that setup_logger doesn't add duplicate handlers"""
        from common.logger import setup_logger

        logger1 = setup_logger('test_no_dup')
        handler_count_1 = len(logger1.handlers)

        # Call again with same name
        logger2 = setup_logger('test_no_dup')
        handler_count_2 = len(logger2.handlers)

        # Should be the same logger with same number of handlers
        assert logger1 is logger2
        assert handler_count_1 == handler_count_2

    def test_setup_logger_propagate_false(self):
        """Test that logger propagate is set to False"""
        from common.logger import setup_logger

        logger = setup_logger('test_propagate')

        assert logger.propagate is False


class TestHTTPLoggingExtended:
    """Extended tests for HTTP logging"""

    def test_log_http_request_debug_level(self):
        """Test HTTP request logging at DEBUG level"""
        from common.logger import setup_logger, log_http_request

        logger = setup_logger('test_http_debug', level='DEBUG')

        # Should log detailed payload at DEBUG level
        log_http_request(
            logger=logger,
            method='POST',
            url='http://example.com/api',
            headers={'Authorization': 'Bearer token'},
            body={'data': 'test'}
        )

    def test_log_http_response_without_duration(self):
        """Test HTTP response logging without duration"""
        from common.logger import setup_logger, log_http_response

        logger = setup_logger('test_http_no_dur', level='INFO')

        # Should not raise exception without duration_ms
        log_http_response(
            logger=logger,
            status_code=200,
            headers={'Content-Type': 'application/json'},
            body={'result': 'success'}
        )

    def test_log_http_response_debug_level(self):
        """Test HTTP response logging at DEBUG level"""
        from common.logger import setup_logger, log_http_response

        logger = setup_logger('test_http_resp_debug', level='DEBUG')

        # Should log detailed payload at DEBUG level
        log_http_response(
            logger=logger,
            status_code=200,
            body={'data': 'response'},
            duration_ms=50.5
        )


class TestA2ALoggingExtended:
    """Extended tests for A2A logging"""

    def test_log_a2a_message_without_peer(self):
        """Test A2A message logging without peer"""
        from common.logger import setup_logger, log_a2a_message

        logger = setup_logger('test_a2a_no_peer', level='INFO')

        # Should not raise exception without peer
        log_a2a_message(
            logger=logger,
            direction='sent',
            message_type='ap2/IntentMandate',
            payload={'mandate': 'data'}
        )

    def test_log_a2a_message_with_headers(self):
        """Test A2A message logging with headers"""
        from common.logger import setup_logger, log_a2a_message

        logger = setup_logger('test_a2a_headers', level='DEBUG')

        # Should log headers at DEBUG level
        log_a2a_message(
            logger=logger,
            direction='received',
            message_type='ap2/CartMandate',
            payload={'cart': 'data'},
            peer='did:ap2:agent:shopping',
            headers={'X-Request-ID': 'req-123'}
        )


class TestMCPLoggingExtended:
    """Extended tests for MCP logging"""

    def test_log_mcp_request_without_url(self):
        """Test MCP request logging without URL"""
        from common.logger import setup_logger, log_mcp_request

        logger = setup_logger('test_mcp_no_url', level='INFO')

        # Should not raise exception without URL
        log_mcp_request(
            logger=logger,
            tool_name='search_products',
            arguments={'query': 'shoes'}
        )

    def test_log_mcp_response_without_duration(self):
        """Test MCP response logging without duration"""
        from common.logger import setup_logger, log_mcp_response

        logger = setup_logger('test_mcp_no_dur', level='INFO')

        # Should not raise exception without duration
        log_mcp_response(
            logger=logger,
            tool_name='search_products',
            result={'products': []}
        )

    def test_log_mcp_request_debug_level(self):
        """Test MCP request logging at DEBUG level with full payload"""
        from common.logger import setup_logger, log_mcp_request

        logger = setup_logger('test_mcp_req_debug', level='DEBUG')

        # Should log detailed payload at DEBUG level (lines 287-294)
        log_mcp_request(
            logger=logger,
            tool_name='search_products',
            arguments={'query': 'shoes', 'limit': 10},
            url='http://mcp-server:8000',
            headers={'X-Request-ID': 'req-123'}
        )

    def test_log_mcp_response_debug_level(self):
        """Test MCP response logging at DEBUG level with full payload"""
        from common.logger import setup_logger, log_mcp_response

        logger = setup_logger('test_mcp_resp_debug', level='DEBUG')

        # Should log detailed payload at DEBUG level (lines 321-328)
        log_mcp_response(
            logger=logger,
            tool_name='search_products',
            result={'products': [{'id': 1, 'name': 'Shoes'}]},
            duration_ms=45.5,
            error=None
        )


class TestCryptoLoggingExtended:
    """Extended tests for crypto logging"""

    def test_log_crypto_operation_without_key_id(self):
        """Test crypto operation logging without key_id"""
        from common.logger import setup_logger, log_crypto_operation

        logger = setup_logger('test_crypto_no_key', level='INFO')

        # Should not raise exception without key_id
        log_crypto_operation(
            logger=logger,
            operation='encrypt',
            algorithm='aes-256-gcm',
            success=True
        )

    def test_log_crypto_decrypt(self):
        """Test crypto decrypt operation logging"""
        from common.logger import setup_logger, log_crypto_operation

        logger = setup_logger('test_crypto_decrypt', level='INFO')

        log_crypto_operation(
            logger=logger,
            operation='decrypt',
            algorithm='rsa-oaep',
            key_id='key-3',
            success=True
        )


class TestDatabaseLoggingExtended:
    """Extended tests for database logging"""

    def test_log_database_operation_without_record_id(self):
        """Test database operation logging without record_id"""
        from common.logger import setup_logger, log_database_operation

        logger = setup_logger('test_db_no_id', level='DEBUG')

        # Should not raise exception without record_id
        log_database_operation(
            logger=logger,
            operation='SELECT',
            table='products',
            duration_ms=3.5
        )

    def test_log_database_update(self):
        """Test database UPDATE logging"""
        from common.logger import setup_logger, log_database_operation

        logger = setup_logger('test_db_update', level='DEBUG')

        log_database_operation(
            logger=logger,
            operation='UPDATE',
            table='users',
            record_id='user_123',
            duration_ms=8.0
        )

    def test_log_database_delete(self):
        """Test database DELETE logging"""
        from common.logger import setup_logger, log_database_operation

        logger = setup_logger('test_db_delete', level='DEBUG')

        log_database_operation(
            logger=logger,
            operation='DELETE',
            table='sessions',
            record_id='session_456'
        )


class TestLoggingAsyncClient:
    """Test LoggingAsyncClient wrapper"""

    @pytest.mark.asyncio
    async def test_logging_async_client_post(self):
        """Test LoggingAsyncClient POST request"""
        from common.logger import setup_logger, LoggingAsyncClient

        logger = setup_logger('test_async_client', level='DEBUG')

        # Mock httpx module that's imported inside LoggingAsyncClient.__init__
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            # Mock response
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.headers = {'Content-Type': 'application/json'}
            mock_response.json.return_value = {'result': 'success'}
            mock_response.text = '{"result": "success"}'
            mock_response.aread = AsyncMock()
            mock_client.request.return_value = mock_response

            client = LoggingAsyncClient(logger, timeout=30.0)

            response = await client.post('http://example.com/api', json={'data': 'test'})

            assert response.status_code == 200
            mock_client.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_logging_async_client_get(self):
        """Test LoggingAsyncClient GET request"""
        from common.logger import setup_logger, LoggingAsyncClient

        logger = setup_logger('test_async_get', level='DEBUG')

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.json.return_value = {'data': 'value'}
            mock_response.aread = AsyncMock()
            mock_client.request.return_value = mock_response

            client = LoggingAsyncClient(logger)

            response = await client.get('http://example.com/data')

            assert response.status_code == 200
            mock_client.request.assert_called_with("GET", 'http://example.com/data')

    @pytest.mark.asyncio
    async def test_logging_async_client_put(self):
        """Test LoggingAsyncClient PUT request"""
        from common.logger import setup_logger, LoggingAsyncClient

        logger = setup_logger('test_async_put', level='DEBUG')

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.headers = {'Content-Type': 'text/plain'}
            mock_response.aread = AsyncMock()
            mock_response.json.side_effect = Exception("Not JSON")
            mock_response.text = "OK"
            mock_client.request.return_value = mock_response

            client = LoggingAsyncClient(logger)

            response = await client.put('http://example.com/resource', json={'update': 'data'})

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_logging_async_client_delete(self):
        """Test LoggingAsyncClient DELETE request"""
        from common.logger import setup_logger, LoggingAsyncClient

        logger = setup_logger('test_async_delete', level='DEBUG')

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            mock_response = AsyncMock()
            mock_response.status_code = 204
            mock_response.headers = {}
            mock_response.aread = AsyncMock()
            mock_response.json.side_effect = Exception("No content")
            mock_response.text = ""
            mock_client.request.return_value = mock_response

            client = LoggingAsyncClient(logger)

            response = await client.delete('http://example.com/resource/123')

            assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_logging_async_client_patch(self):
        """Test LoggingAsyncClient PATCH request"""
        from common.logger import setup_logger, LoggingAsyncClient

        logger = setup_logger('test_async_patch', level='DEBUG')

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.headers = {'Content-Type': 'application/json'}
            mock_response.aread = AsyncMock()
            mock_response.json.return_value = {'patched': True}
            mock_client.request.return_value = mock_response

            client = LoggingAsyncClient(logger)

            response = await client.patch('http://example.com/resource/123', json={'field': 'value'})

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_logging_async_client_with_data(self):
        """Test LoggingAsyncClient with data parameter"""
        from common.logger import setup_logger, LoggingAsyncClient

        logger = setup_logger('test_async_data', level='DEBUG')

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.aread = AsyncMock()
            mock_response.json.return_value = {}
            mock_client.request.return_value = mock_response

            client = LoggingAsyncClient(logger)

            response = await client.post('http://example.com/form', data={'key': 'value'})

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_logging_async_client_with_content(self):
        """Test LoggingAsyncClient with content parameter"""
        from common.logger import setup_logger, LoggingAsyncClient

        logger = setup_logger('test_async_content', level='DEBUG')

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.aread = AsyncMock()
            mock_response.json.return_value = {}
            mock_client.request.return_value = mock_response

            client = LoggingAsyncClient(logger)

            response = await client.post('http://example.com/upload', content=b'binary data')

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_logging_async_client_aclose(self):
        """Test LoggingAsyncClient aclose method"""
        from common.logger import setup_logger, LoggingAsyncClient

        logger = setup_logger('test_async_close', level='DEBUG')

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            client = LoggingAsyncClient(logger)

            await client.aclose()

            mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_logging_async_client_getattr(self):
        """Test LoggingAsyncClient attribute delegation"""
        from common.logger import setup_logger, LoggingAsyncClient

        logger = setup_logger('test_async_attr', level='DEBUG')

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.timeout = 30.0
            mock_client_class.return_value = mock_client

            client = LoggingAsyncClient(logger)

            # Access attribute that should be delegated
            timeout = client.timeout

            assert timeout == 30.0

    @pytest.mark.asyncio
    async def test_logging_async_client_content_decode_exception(self):
        """Test LoggingAsyncClient with content that raises decode exception"""
        from common.logger import setup_logger, LoggingAsyncClient

        logger = setup_logger('test_async_content_exception', level='DEBUG')

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.aread = AsyncMock()
            mock_response.json.return_value = {}
            mock_client.request.return_value = mock_response

            client = LoggingAsyncClient(logger)

            # Create a class that fools isinstance and raises on decode
            class BytesLike:
                """Class that appears as bytes to isinstance but raises on decode"""
                __class__ = bytes

                def decode(self, encoding='utf-8'):
                    raise UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid start byte')

            # This should trigger lines 440-441 (except block)
            response = await client.post('http://example.com/upload', content=BytesLike())

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_logging_async_client_response_text_exception(self):
        """Test LoggingAsyncClient when both response.json() and response.text raise exceptions"""
        from common.logger import setup_logger, LoggingAsyncClient

        logger = setup_logger('test_async_response_exception', level='DEBUG')

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            # Create a mock response where both json() and text raise exceptions
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.aread = AsyncMock()
            # Both json() and text should raise exceptions to trigger lines 464-468
            mock_response.json.side_effect = Exception("JSON parse error")

            # Make text property raise exception when accessed
            type(mock_response).text = property(lambda self: (_ for _ in ()).throw(Exception("Text decode error")))

            mock_client.request.return_value = mock_response

            client = LoggingAsyncClient(logger)

            # This should trigger lines 464-468 (nested exception handling)
            response = await client.get('http://example.com/binary')

            assert response.status_code == 200
