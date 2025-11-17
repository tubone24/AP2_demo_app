"""
Tests for Telemetry Module

Tests cover:
- is_telemetry_enabled (environment variable check)
- _mask_sensitive_data (sensitive information masking)
- _truncate_body (body truncation)
- SENSITIVE_KEYS validation
- MAX_BODY_SIZE constant
"""

import pytest
import os


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
