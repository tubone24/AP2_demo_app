"""
Tests for Auth

Tests cover:
- Password validation and hashing
- JWT token creation and validation
- Authentication helpers
"""

import pytest
import jwt as pyjwt
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException

from common.auth import (
    validate_password_strength,
    hash_password,
    verify_password,
    create_access_token,
    verify_access_token,
    SECRET_KEY,
    ALGORITHM,
)


class TestPasswordValidation:
    """Test password validation functions"""

    def test_validate_password_strength_valid(self):
        """Test valid password passes validation"""
        # Valid password: 8+ chars, uppercase, lowercase, digit
        assert validate_password_strength("Test1234") is True
        assert validate_password_strength("SecurePass123") is True

    def test_validate_password_strength_too_short(self):
        """Test password too short raises exception"""
        with pytest.raises(HTTPException) as exc_info:
            validate_password_strength("Test1")
        assert exc_info.value.status_code == 400
        assert "at least 8 characters" in exc_info.value.detail

    def test_validate_password_strength_no_uppercase(self):
        """Test password without uppercase raises exception"""
        with pytest.raises(HTTPException) as exc_info:
            validate_password_strength("test1234")
        assert exc_info.value.status_code == 400
        assert "uppercase, lowercase, and digits" in exc_info.value.detail

    def test_validate_password_strength_no_lowercase(self):
        """Test password without lowercase raises exception"""
        with pytest.raises(HTTPException) as exc_info:
            validate_password_strength("TEST1234")
        assert exc_info.value.status_code == 400

    def test_validate_password_strength_no_digit(self):
        """Test password without digit raises exception"""
        with pytest.raises(HTTPException) as exc_info:
            validate_password_strength("TestTest")
        assert exc_info.value.status_code == 400

    def test_validate_password_strength_weak_password(self):
        """Test weak passwords are rejected"""
        weak_passwords = ["Password1", "Qwerty123", "Admin123"]
        for weak_pass in weak_passwords:
            with pytest.raises(HTTPException) as exc_info:
                validate_password_strength(weak_pass)
            assert exc_info.value.status_code == 400
            assert "too weak" in exc_info.value.detail


class TestPasswordHashing:
    """Test password hashing functions"""

    def test_hash_password(self):
        """Test password hashing"""
        password = "TestPass123"
        hashed = hash_password(password)

        # Should produce Argon2id hash
        assert isinstance(hashed, str)
        assert hashed.startswith("$argon2")
        assert hashed != password

    def test_verify_password_correct(self):
        """Test password verification with correct password"""
        password = "TestPass123"
        hashed = hash_password(password)

        # Correct password should verify
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test password verification with incorrect password"""
        password = "TestPass123"
        hashed = hash_password(password)

        # Incorrect password should not verify
        assert verify_password("WrongPass123", hashed) is False

    def test_hash_password_unique_salts(self):
        """Test that same password produces different hashes (unique salts)"""
        password = "TestPass123"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        # Hashes should be different due to unique salts
        assert hash1 != hash2
        # But both should verify
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True


class TestJWTTokens:
    """Test JWT token creation and validation"""

    def test_create_access_token(self):
        """Test JWT token creation"""
        data = {"user_id": "user_123", "email": "test@example.com"}
        token = create_access_token(data)

        # Should produce JWT token
        assert isinstance(token, str)
        assert len(token.split('.')) == 3  # JWT has 3 parts

        # Decode and verify contents
        payload = pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["user_id"] == "user_123"
        assert payload["email"] == "test@example.com"
        assert "exp" in payload

    def test_create_access_token_with_custom_expiry(self):
        """Test JWT token with custom expiry"""
        data = {"user_id": "user_123"}
        expires_delta = timedelta(minutes=30)
        token = create_access_token(data, expires_delta=expires_delta)

        # Decode and check expiry
        payload = pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)

        # Should expire in approximately 30 minutes
        time_diff = (exp_time - now).total_seconds()
        assert 29 * 60 < time_diff < 31 * 60  # Allow 1 minute tolerance

    def test_verify_access_token_valid(self):
        """Test verification of valid token"""
        data = {"user_id": "user_123", "email": "test@example.com"}
        token = create_access_token(data)

        # Should verify successfully
        token_data = verify_access_token(token)
        assert token_data.user_id == "user_123"
        assert token_data.email == "test@example.com"

    def test_verify_access_token_expired(self):
        """Test verification of expired token"""
        data = {"user_id": "user_123"}
        # Create token that expires immediately
        expires_delta = timedelta(seconds=-1)
        token = create_access_token(data, expires_delta=expires_delta)

        # Should raise exception for expired token
        with pytest.raises(HTTPException) as exc_info:
            verify_access_token(token)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_verify_access_token_invalid(self):
        """Test verification of invalid token"""
        invalid_token = "invalid.token.here"

        # Should raise exception for invalid token
        with pytest.raises(HTTPException) as exc_info:
            verify_access_token(invalid_token)
        assert exc_info.value.status_code == 401

    def test_verify_access_token_missing_user_id(self):
        """Test verification of token without user_id"""
        # Create token without user_id
        data = {"email": "test@example.com"}
        payload = data.copy()
        payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=30)
        token = pyjwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

        # Should raise exception
        with pytest.raises(HTTPException) as exc_info:
            verify_access_token(token)
        assert exc_info.value.status_code == 401
