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
"""

import pytest
import logging
import json
import os
from io import StringIO


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
