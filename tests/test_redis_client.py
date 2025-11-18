"""
Tests for Redis Client

Tests cover:
- Redis KV operations (set, get, delete, exists)
- TTL management
- Token store functionality
- Session store functionality
- Key pattern matching
- JSON serialization/deserialization
- Error handling
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from common.redis_client import RedisClient, TokenStore, SessionStore


class TestRedisClientBasicOperations:
    """Test basic Redis client operations"""

    @pytest.mark.asyncio
    async def test_redis_client_initialization(self):
        """Test RedisClient initialization"""
        client = RedisClient("redis://localhost:6379/0")
        assert client.redis_url == "redis://localhost:6379/0"
        assert client.client is None

    @pytest.mark.asyncio
    async def test_redis_client_initialization_default_url(self):
        """Test RedisClient initialization with default URL"""
        client = RedisClient()
        assert client.redis_url == "redis://localhost:6379/0"
        assert client.client is None

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful Redis connection"""
        client = RedisClient("redis://localhost:6379/0")

        # Mock redis.from_url as an async function
        mock_redis = AsyncMock()
        with patch('common.redis_client.redis.from_url', new=AsyncMock(return_value=mock_redis)) as mock_from_url:
            await client.connect()

            # Verify from_url was called with correct parameters
            mock_from_url.assert_called_once_with(
                "redis://localhost:6379/0",
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0
            )

            # Verify client was set
            assert client.client == mock_redis

    @pytest.mark.asyncio
    async def test_connect_already_connected(self):
        """Test connect when already connected"""
        client = RedisClient("redis://localhost:6379/0")

        # Mock existing connection
        existing_client = AsyncMock()
        client.client = existing_client

        with patch('common.redis_client.redis.from_url') as mock_from_url:
            await client.connect()

            # Should not create new connection
            mock_from_url.assert_not_called()
            assert client.client == existing_client

    @pytest.mark.asyncio
    async def test_disconnect_success(self):
        """Test successful Redis disconnection"""
        client = RedisClient()

        # Mock connected client
        mock_redis = AsyncMock()
        client.client = mock_redis

        await client.disconnect()

        # Verify close was called and client was set to None
        mock_redis.close.assert_called_once()
        assert client.client is None

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self):
        """Test disconnect when not connected"""
        client = RedisClient()

        # Should not raise an error
        await client.disconnect()
        assert client.client is None


class TestRedisSetOperation:
    """Test Redis SET operations"""

    @pytest.mark.asyncio
    async def test_set_dict_with_ttl(self):
        """Test SET operation with dict value and TTL"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        test_data = {"user_id": "user_001", "amount": 8000}

        result = await client.set("test_key", test_data, ttl_seconds=900)

        # Verify setex was called with JSON serialized data
        expected_value = json.dumps(test_data, ensure_ascii=False)
        mock_redis.setex.assert_called_once_with("test_key", 900, expected_value)
        assert result is True

    @pytest.mark.asyncio
    async def test_set_dict_without_ttl(self):
        """Test SET operation with dict value without TTL"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        test_data = {"key": "value"}

        result = await client.set("test_key", test_data)

        # Verify set was called (not setex)
        expected_value = json.dumps(test_data, ensure_ascii=False)
        mock_redis.set.assert_called_once_with("test_key", expected_value)
        assert result is True

    @pytest.mark.asyncio
    async def test_set_list_value(self):
        """Test SET operation with list value"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        test_data = ["item1", "item2", "item3"]

        result = await client.set("test_key", test_data, ttl_seconds=300)

        # Verify list was JSON serialized
        expected_value = json.dumps(test_data, ensure_ascii=False)
        mock_redis.setex.assert_called_once_with("test_key", 300, expected_value)
        assert result is True

    @pytest.mark.asyncio
    async def test_set_string_value(self):
        """Test SET operation with string value"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        result = await client.set("test_key", "simple_string", ttl_seconds=600)

        # Verify string was stored as-is
        mock_redis.setex.assert_called_once_with("test_key", 600, "simple_string")
        assert result is True

    @pytest.mark.asyncio
    async def test_set_integer_value(self):
        """Test SET operation with integer value"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        result = await client.set("test_key", 12345)

        # Verify integer was converted to string
        mock_redis.set.assert_called_once_with("test_key", "12345")
        assert result is True

    @pytest.mark.asyncio
    async def test_set_error_handling(self):
        """Test SET operation error handling"""
        client = RedisClient()

        # Mock Redis client that raises exception
        mock_redis = AsyncMock()
        mock_redis.setex.side_effect = Exception("Redis error")
        client.client = mock_redis

        result = await client.set("test_key", {"data": "test"}, ttl_seconds=300)

        # Should return False on error
        assert result is False

    @pytest.mark.asyncio
    async def test_set_connects_if_not_connected(self):
        """Test SET operation connects automatically"""
        client = RedisClient()

        # Mock redis.from_url as an async function
        mock_redis = AsyncMock()
        with patch('common.redis_client.redis.from_url', new=AsyncMock(return_value=mock_redis)):
            result = await client.set("test_key", "value", ttl_seconds=100)

            # Verify connection was established
            assert client.client == mock_redis
            mock_redis.setex.assert_called_once()
            assert result is True


class TestRedisGetOperation:
    """Test Redis GET operations"""

    @pytest.mark.asyncio
    async def test_get_json_success(self):
        """Test GET operation with JSON parsing"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        test_data = {"user_id": "user_001", "amount": 8000}
        mock_redis.get.return_value = json.dumps(test_data)
        client.client = mock_redis

        result = await client.get("test_key", as_json=True)

        # Verify JSON was parsed correctly
        mock_redis.get.assert_called_once_with("test_key")
        assert result == test_data

    @pytest.mark.asyncio
    async def test_get_string_with_json_flag(self):
        """Test GET operation with as_json=True but invalid JSON"""
        client = RedisClient()

        # Mock Redis client returning non-JSON string
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "not_json_string"
        client.client = mock_redis

        result = await client.get("test_key", as_json=True)

        # Should return string when JSON parsing fails
        assert result == "not_json_string"

    @pytest.mark.asyncio
    async def test_get_as_string(self):
        """Test GET operation without JSON parsing"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "raw_string_value"
        client.client = mock_redis

        result = await client.get("test_key", as_json=False)

        # Should return raw string
        assert result == "raw_string_value"

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self):
        """Test GET operation with nonexistent key"""
        client = RedisClient()

        # Mock Redis client returning None
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        client.client = mock_redis

        result = await client.get("nonexistent_key")

        # Should return None
        assert result is None

    @pytest.mark.asyncio
    async def test_get_error_handling(self):
        """Test GET operation error handling"""
        client = RedisClient()

        # Mock Redis client that raises exception
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = Exception("Redis error")
        client.client = mock_redis

        result = await client.get("test_key")

        # Should return None on error
        assert result is None

    @pytest.mark.asyncio
    async def test_get_connects_if_not_connected(self):
        """Test GET operation connects automatically"""
        client = RedisClient()

        # Mock redis.from_url as an async function
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps({"test": "data"})

        with patch('common.redis_client.redis.from_url', new=AsyncMock(return_value=mock_redis)):
            result = await client.get("test_key")

            # Verify connection was established
            assert client.client == mock_redis
            mock_redis.get.assert_called_once_with("test_key")


class TestRedisDeleteOperation:
    """Test Redis DELETE operations"""

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """Test successful DELETE operation"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.delete.return_value = 1  # 1 key deleted
        client.client = mock_redis

        result = await client.delete("test_key")

        mock_redis.delete.assert_called_once_with("test_key")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key(self):
        """Test DELETE operation on nonexistent key"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.delete.return_value = 0  # 0 keys deleted
        client.client = mock_redis

        result = await client.delete("nonexistent_key")

        # Should return False when no keys deleted
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_error_handling(self):
        """Test DELETE operation error handling"""
        client = RedisClient()

        # Mock Redis client that raises exception
        mock_redis = AsyncMock()
        mock_redis.delete.side_effect = Exception("Redis error")
        client.client = mock_redis

        result = await client.delete("test_key")

        # Should return False on error
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_connects_if_not_connected(self):
        """Test DELETE operation connects automatically"""
        client = RedisClient()

        # Mock redis.from_url as an async function
        mock_redis = AsyncMock()
        mock_redis.delete.return_value = 1

        with patch('common.redis_client.redis.from_url', new=AsyncMock(return_value=mock_redis)):
            result = await client.delete("test_key")

            # Verify connection was established
            assert client.client == mock_redis
            assert result is True


class TestRedisExistsOperation:
    """Test Redis EXISTS operations"""

    @pytest.mark.asyncio
    async def test_exists_key_found(self):
        """Test EXISTS operation when key exists"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.exists.return_value = 1  # Key exists
        client.client = mock_redis

        result = await client.exists("test_key")

        mock_redis.exists.assert_called_once_with("test_key")
        assert result is True

    @pytest.mark.asyncio
    async def test_exists_key_not_found(self):
        """Test EXISTS operation when key doesn't exist"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.exists.return_value = 0  # Key doesn't exist
        client.client = mock_redis

        result = await client.exists("nonexistent_key")

        assert result is False

    @pytest.mark.asyncio
    async def test_exists_error_handling(self):
        """Test EXISTS operation error handling"""
        client = RedisClient()

        # Mock Redis client that raises exception
        mock_redis = AsyncMock()
        mock_redis.exists.side_effect = Exception("Redis error")
        client.client = mock_redis

        result = await client.exists("test_key")

        # Should return False on error
        assert result is False


class TestRedisTTLOperations:
    """Test Redis TTL operations"""

    @pytest.mark.asyncio
    async def test_get_ttl_with_ttl_set(self):
        """Test GET TTL when TTL is set"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.ttl.return_value = 300  # 300 seconds remaining
        client.client = mock_redis

        result = await client.get_ttl("test_key")

        mock_redis.ttl.assert_called_once_with("test_key")
        assert result == 300

    @pytest.mark.asyncio
    async def test_get_ttl_no_ttl_set(self):
        """Test GET TTL when no TTL is set"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.ttl.return_value = -1  # No TTL
        client.client = mock_redis

        result = await client.get_ttl("test_key")

        # Should return -1
        assert result == -1

    @pytest.mark.asyncio
    async def test_get_ttl_key_not_exists(self):
        """Test GET TTL when key doesn't exist"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.ttl.return_value = -2  # Key doesn't exist
        client.client = mock_redis

        result = await client.get_ttl("nonexistent_key")

        # Should return None for nonexistent key
        assert result is None

    @pytest.mark.asyncio
    async def test_get_ttl_error_handling(self):
        """Test GET TTL error handling"""
        client = RedisClient()

        # Mock Redis client that raises exception
        mock_redis = AsyncMock()
        mock_redis.ttl.side_effect = Exception("Redis error")
        client.client = mock_redis

        result = await client.get_ttl("test_key")

        # Should return None on error
        assert result is None


class TestRedisKeysOperation:
    """Test Redis KEYS operations"""

    @pytest.mark.asyncio
    async def test_keys_pattern_match(self):
        """Test KEYS operation with pattern"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.keys.return_value = ["token:at_001", "token:at_002", "token:at_003"]
        client.client = mock_redis

        result = await client.keys("token:*")

        mock_redis.keys.assert_called_once_with("token:*")
        assert len(result) == 3
        assert "token:at_001" in result

    @pytest.mark.asyncio
    async def test_keys_default_pattern(self):
        """Test KEYS operation with default pattern"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.keys.return_value = ["key1", "key2"]
        client.client = mock_redis

        result = await client.keys()

        # Should use "*" as default pattern
        mock_redis.keys.assert_called_once_with("*")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_keys_no_matches(self):
        """Test KEYS operation with no matches"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.keys.return_value = []
        client.client = mock_redis

        result = await client.keys("nonexistent:*")

        # Should return empty list
        assert result == []

    @pytest.mark.asyncio
    async def test_keys_error_handling(self):
        """Test KEYS operation error handling"""
        client = RedisClient()

        # Mock Redis client that raises exception
        mock_redis = AsyncMock()
        mock_redis.keys.side_effect = Exception("Redis error")
        client.client = mock_redis

        result = await client.keys("test:*")

        # Should return empty list on error
        assert result == []


class TestTokenStore:
    """Test TokenStore functionality"""

    @pytest.mark.asyncio
    async def test_token_store_initialization(self):
        """Test TokenStore initialization"""
        redis_client = RedisClient()
        token_store = TokenStore(redis_client, prefix="token")

        assert token_store.redis == redis_client
        assert token_store.prefix == "token"
        assert token_store.default_ttl == 15 * 60  # 15 minutes

    @pytest.mark.asyncio
    async def test_token_store_default_prefix(self):
        """Test TokenStore with default prefix"""
        redis_client = RedisClient()
        token_store = TokenStore(redis_client)

        assert token_store.prefix == "token"

    @pytest.mark.asyncio
    async def test_make_key(self):
        """Test token key generation"""
        redis_client = RedisClient()
        token_store = TokenStore(redis_client, prefix="token")

        key = token_store._make_key("at_xxxxxxxxxxxxx")

        assert key == "token:at_xxxxxxxxxxxxx"

    @pytest.mark.asyncio
    async def test_save_token_with_default_ttl(self):
        """Test save token with default TTL"""
        redis_client = RedisClient()
        token_store = TokenStore(redis_client)

        # Mock Redis client
        mock_redis = AsyncMock()
        redis_client.client = mock_redis

        token_data = {
            "token_type": "agent_token",
            "payment_method_id": "pm_001",
            "payer_id": "user_001"
        }

        result = await token_store.save_token("at_test", token_data)

        # Verify set was called with correct parameters
        expected_key = "token:at_test"
        expected_value = json.dumps(token_data, ensure_ascii=False)
        mock_redis.setex.assert_called_once_with(expected_key, 900, expected_value)
        assert result is True

    @pytest.mark.asyncio
    async def test_save_token_with_custom_ttl(self):
        """Test save token with custom TTL"""
        redis_client = RedisClient()
        token_store = TokenStore(redis_client)

        # Mock Redis client
        mock_redis = AsyncMock()
        redis_client.client = mock_redis

        token_data = {"data": "test"}

        result = await token_store.save_token("at_test", token_data, ttl_seconds=300)

        # Verify custom TTL was used
        expected_value = json.dumps(token_data, ensure_ascii=False)
        mock_redis.setex.assert_called_once_with("token:at_test", 300, expected_value)

    @pytest.mark.asyncio
    async def test_get_token_success(self):
        """Test get token success"""
        redis_client = RedisClient()
        token_store = TokenStore(redis_client)

        # Mock Redis client
        mock_redis = AsyncMock()
        token_data = {"token_type": "agent_token", "payer_id": "user_001"}
        mock_redis.get.return_value = json.dumps(token_data)
        redis_client.client = mock_redis

        result = await token_store.get_token("at_test")

        mock_redis.get.assert_called_once_with("token:at_test")
        assert result == token_data

    @pytest.mark.asyncio
    async def test_get_token_not_found(self):
        """Test get token when not found"""
        redis_client = RedisClient()
        token_store = TokenStore(redis_client)

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        redis_client.client = mock_redis

        result = await token_store.get_token("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_token_success(self):
        """Test delete token success"""
        redis_client = RedisClient()
        token_store = TokenStore(redis_client)

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.delete.return_value = 1
        redis_client.client = mock_redis

        result = await token_store.delete_token("at_test")

        mock_redis.delete.assert_called_once_with("token:at_test")
        assert result is True


class TestSessionStore:
    """Test SessionStore functionality"""

    @pytest.mark.asyncio
    async def test_session_store_initialization(self):
        """Test SessionStore initialization"""
        redis_client = RedisClient()
        session_store = SessionStore(redis_client, prefix="session")

        assert session_store.redis == redis_client
        assert session_store.prefix == "session"
        assert session_store.default_ttl == 10 * 60  # 10 minutes

    @pytest.mark.asyncio
    async def test_session_store_default_prefix(self):
        """Test SessionStore with default prefix"""
        redis_client = RedisClient()
        session_store = SessionStore(redis_client)

        assert session_store.prefix == "session"

    @pytest.mark.asyncio
    async def test_make_session_key(self):
        """Test session key generation"""
        redis_client = RedisClient()
        session_store = SessionStore(redis_client)

        key = session_store._make_key("sess_001")

        assert key == "session:sess_001"

    @pytest.mark.asyncio
    async def test_save_session_with_default_ttl(self):
        """Test save session with default TTL"""
        redis_client = RedisClient()
        session_store = SessionStore(redis_client)

        # Mock Redis client
        mock_redis = AsyncMock()
        redis_client.client = mock_redis

        session_data = {
            "user_id": "user_001",
            "state": "active",
            "step_up_completed": False
        }

        result = await session_store.save_session("sess_001", session_data)

        # Verify set was called with correct parameters
        expected_value = json.dumps(session_data, ensure_ascii=False)
        mock_redis.setex.assert_called_once_with("session:sess_001", 600, expected_value)
        assert result is True

    @pytest.mark.asyncio
    async def test_save_session_with_custom_ttl(self):
        """Test save session with custom TTL"""
        redis_client = RedisClient()
        session_store = SessionStore(redis_client)

        # Mock Redis client
        mock_redis = AsyncMock()
        redis_client.client = mock_redis

        session_data = {"user_id": "user_001"}

        result = await session_store.save_session("sess_001", session_data, ttl_seconds=60)

        # Verify custom TTL was used (60 seconds for WebAuthn challenge)
        expected_value = json.dumps(session_data, ensure_ascii=False)
        mock_redis.setex.assert_called_once_with("session:sess_001", 60, expected_value)

    @pytest.mark.asyncio
    async def test_get_session_success(self):
        """Test get session success"""
        redis_client = RedisClient()
        session_store = SessionStore(redis_client)

        # Mock Redis client
        mock_redis = AsyncMock()
        session_data = {"user_id": "user_001", "state": "active"}
        mock_redis.get.return_value = json.dumps(session_data)
        redis_client.client = mock_redis

        result = await session_store.get_session("sess_001")

        mock_redis.get.assert_called_once_with("session:sess_001")
        assert result == session_data

    @pytest.mark.asyncio
    async def test_get_session_not_found(self):
        """Test get session when not found"""
        redis_client = RedisClient()
        session_store = SessionStore(redis_client)

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        redis_client.client = mock_redis

        result = await session_store.get_session("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_session_success(self):
        """Test delete session success"""
        redis_client = RedisClient()
        session_store = SessionStore(redis_client)

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.delete.return_value = 1
        redis_client.client = mock_redis

        result = await session_store.delete_session("sess_001")

        mock_redis.delete.assert_called_once_with("session:sess_001")
        assert result is True

    @pytest.mark.asyncio
    async def test_update_session_success_with_ttl(self):
        """Test update session success preserving TTL"""
        redis_client = RedisClient()
        session_store = SessionStore(redis_client)

        # Mock Redis client
        mock_redis = AsyncMock()

        # Existing session data
        existing_data = {"user_id": "user_001", "step_up_completed": False}
        mock_redis.get.return_value = json.dumps(existing_data)
        mock_redis.ttl.return_value = 300  # 300 seconds remaining
        redis_client.client = mock_redis

        # Update data
        updates = {"step_up_completed": True, "step_up_timestamp": "2024-01-01T00:00:00"}

        result = await session_store.update_session("sess_001", updates)

        # Verify get and ttl were called
        mock_redis.get.assert_called_once_with("session:sess_001")
        mock_redis.ttl.assert_called_once_with("session:sess_001")

        # Verify merged data was saved with preserved TTL
        expected_merged = {
            "user_id": "user_001",
            "step_up_completed": True,
            "step_up_timestamp": "2024-01-01T00:00:00"
        }
        expected_value = json.dumps(expected_merged, ensure_ascii=False)
        mock_redis.setex.assert_called_once_with("session:sess_001", 300, expected_value)
        assert result is True

    @pytest.mark.asyncio
    async def test_update_session_success_with_default_ttl(self):
        """Test update session when TTL is expired or not set"""
        redis_client = RedisClient()
        session_store = SessionStore(redis_client)

        # Mock Redis client
        mock_redis = AsyncMock()

        # Existing session data
        existing_data = {"user_id": "user_001"}
        mock_redis.get.return_value = json.dumps(existing_data)
        mock_redis.ttl.return_value = -1  # No TTL set
        redis_client.client = mock_redis

        # Update data
        updates = {"state": "active"}

        result = await session_store.update_session("sess_001", updates)

        # Verify merged data was saved with default TTL
        expected_merged = {"user_id": "user_001", "state": "active"}
        expected_value = json.dumps(expected_merged, ensure_ascii=False)
        mock_redis.setex.assert_called_once_with("session:sess_001", 600, expected_value)
        assert result is True

    @pytest.mark.asyncio
    async def test_update_session_not_found(self):
        """Test update session when session doesn't exist"""
        redis_client = RedisClient()
        session_store = SessionStore(redis_client)

        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        redis_client.client = mock_redis

        result = await session_store.update_session("nonexistent", {"state": "active"})

        # Should return False when session doesn't exist
        assert result is False


class TestJSONSerialization:
    """Test JSON serialization and deserialization"""

    @pytest.mark.asyncio
    async def test_dict_serialization(self):
        """Test dict value is JSON serialized"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        test_dict = {"key": "value", "number": 123}

        await client.set("test", test_dict)

        # Verify JSON serialization
        expected_json = json.dumps(test_dict, ensure_ascii=False)
        mock_redis.set.assert_called_once_with("test", expected_json)

    @pytest.mark.asyncio
    async def test_list_serialization(self):
        """Test list value is JSON serialized"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        test_list = ["item1", "item2", "item3"]

        await client.set("test", test_list)

        # Verify JSON serialization
        expected_json = json.dumps(test_list, ensure_ascii=False)
        mock_redis.set.assert_called_once_with("test", expected_json)

    @pytest.mark.asyncio
    async def test_complex_nested_serialization(self):
        """Test complex nested structure serialization"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        complex_data = {
            "mandate": {
                "type": "PaymentMandate",
                "amount": {"value": "8000.00", "currency": "JPY"}
            },
            "items": ["item1", "item2"]
        }

        await client.set("test", complex_data, ttl_seconds=100)

        # Verify complex structure was serialized
        expected_json = json.dumps(complex_data, ensure_ascii=False)
        mock_redis.setex.assert_called_once_with("test", 100, expected_json)

    @pytest.mark.asyncio
    async def test_json_deserialization(self):
        """Test JSON deserialization on get"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        test_data = {"key": "value", "nested": {"data": 123}}
        mock_redis.get.return_value = json.dumps(test_data)
        client.client = mock_redis

        result = await client.get("test", as_json=True)

        # Verify deserialization
        assert result == test_data
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_unicode_serialization(self):
        """Test Unicode characters are preserved"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        unicode_data = {"message": "こんにちは", "currency": "JPY"}

        await client.set("test", unicode_data)

        # Verify ensure_ascii=False preserves Unicode
        expected_json = json.dumps(unicode_data, ensure_ascii=False)
        mock_redis.set.assert_called_once_with("test", expected_json)
        assert "こんにちは" in expected_json


class TestEdgeCases:
    """Test edge cases and error scenarios"""

    @pytest.mark.asyncio
    async def test_empty_dict(self):
        """Test storing empty dict"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        result = await client.set("test", {})

        expected_json = json.dumps({}, ensure_ascii=False)
        mock_redis.set.assert_called_once_with("test", expected_json)
        assert result is True

    @pytest.mark.asyncio
    async def test_empty_list(self):
        """Test storing empty list"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        result = await client.set("test", [])

        expected_json = json.dumps([], ensure_ascii=False)
        mock_redis.set.assert_called_once_with("test", expected_json)
        assert result is True

    @pytest.mark.asyncio
    async def test_none_value(self):
        """Test storing None value"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        result = await client.set("test", None)

        # None should be converted to string "None"
        mock_redis.set.assert_called_once_with("test", "None")
        assert result is True

    @pytest.mark.asyncio
    async def test_boolean_value(self):
        """Test storing boolean value"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        result = await client.set("test", True)

        # Boolean should be converted to string
        mock_redis.set.assert_called_once_with("test", "True")
        assert result is True

    @pytest.mark.asyncio
    async def test_zero_ttl(self):
        """Test TTL with zero value"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        # TTL of 0 is falsy, should use set instead of setex
        result = await client.set("test", "value", ttl_seconds=0)

        # Should use set, not setex
        mock_redis.set.assert_called_once_with("test", "value")
        assert result is True

    @pytest.mark.asyncio
    async def test_large_ttl(self):
        """Test large TTL value"""
        client = RedisClient()

        # Mock Redis client
        mock_redis = AsyncMock()
        client.client = mock_redis

        large_ttl = 86400 * 30  # 30 days
        result = await client.set("test", "value", ttl_seconds=large_ttl)

        mock_redis.setex.assert_called_once_with("test", large_ttl, "value")
        assert result is True
