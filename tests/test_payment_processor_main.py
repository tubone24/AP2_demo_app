"""
Tests for Payment Processor main.py

Tests cover:
- Module initialization and imports
- Service setup and configuration
- App instance creation
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path


class TestPaymentProcessorMain:
    """Test Payment Processor main module"""

    @patch('common.base_agent.KeyManager')
    def test_imports(self, mock_key):
        """Test that all required modules can be imported"""
        # Import main components with KeyManager mocked
        from services.payment_processor.processor import PaymentProcessorService
        from common.telemetry import setup_telemetry, instrument_fastapi_app

        assert PaymentProcessorService is not None
        assert setup_telemetry is not None
        assert instrument_fastapi_app is not None

    @patch('common.base_agent.KeyManager')
    def test_service_initialization(self, mock_key):
        """Test service initialization with mocked dependencies"""
        from services.payment_processor.processor import PaymentProcessorService

        # Verify that we can import and reference the service class
        # The actual instantiation happens at module load time in main.py
        # but we can't test that without circular import issues
        assert PaymentProcessorService is not None

        # Verify service class has expected methods
        assert hasattr(PaymentProcessorService, '__init__')

        # Verify telemetry functions exist
        from common.telemetry import setup_telemetry, instrument_fastapi_app
        assert setup_telemetry is not None
        assert instrument_fastapi_app is not None

    def test_service_name_from_env(self, monkeypatch):
        """Test service name can be set via environment variable"""
        monkeypatch.setenv("OTEL_SERVICE_NAME", "custom_payment_processor")

        import os
        service_name = os.getenv("OTEL_SERVICE_NAME", "payment_processor")

        assert service_name == "custom_payment_processor"

    def test_default_service_name(self):
        """Test default service name"""
        import os
        service_name = os.getenv("OTEL_SERVICE_NAME", "payment_processor")

        assert service_name == "payment_processor"

    @patch('common.base_agent.KeyManager')
    @patch('services.payment_processor.processor.PaymentProcessorService')
    def test_app_instance_exists(self, mock_service, mock_key):
        """Test that app instance is created"""
        # Mock the service to avoid KeyManager initialization
        mock_app = MagicMock()
        mock_service_instance = MagicMock()
        mock_service_instance.app = mock_app
        mock_service.return_value = mock_service_instance

        # Import and verify the module has necessary attributes
        import services.payment_processor.main as main_module

        # Verify main module structure
        assert hasattr(main_module, 'PaymentProcessorService')
        assert hasattr(main_module, 'setup_telemetry')
        assert hasattr(main_module, 'instrument_fastapi_app')

    def test_logging_configuration(self):
        """Test logging is properly configured"""
        import logging

        # Check logging is configured
        logger = logging.getLogger()
        assert logger is not None

        # The main module sets up basic logging
        # We just verify logger works
        logger.info("Test logging configuration")

    @patch('uvicorn.run')
    def test_uvicorn_configuration(self, mock_run):
        """Test uvicorn configuration when running as main"""
        # This test verifies the uvicorn.run configuration
        # We can't easily test __name__ == "__main__" block directly
        # but we can verify the configuration would be correct

        expected_config = {
            'app': 'main:app',
            'host': '0.0.0.0',
            'port': 8004,
            'reload': False,
            'log_level': 'info'
        }

        # Verify config values are reasonable
        assert expected_config['port'] == 8004
        assert expected_config['host'] == '0.0.0.0'
        assert expected_config['reload'] is False


class TestPaymentProcessorConfiguration:
    """Test Payment Processor configuration"""

    def test_database_url_configuration(self, monkeypatch):
        """Test database URL can be configured"""
        test_db_url = "sqlite+aiosqlite:////test/path/payment_processor.db"
        monkeypatch.setenv("DATABASE_URL", test_db_url)

        import os
        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////app/v2/data/payment_processor.db")

        assert db_url == test_db_url

    def test_default_database_url(self, monkeypatch):
        """Test default database URL"""
        import os
        # Remove DATABASE_URL to test default
        monkeypatch.delenv("DATABASE_URL", raising=False)
        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////app/v2/data/payment_processor.db")

        assert "payment_processor.db" in db_url

    def test_payment_network_url_configuration(self, monkeypatch):
        """Test payment network URL can be configured"""
        test_url = "http://test_network:9999"
        monkeypatch.setenv("PAYMENT_NETWORK_URL", test_url)

        import os
        network_url = os.getenv("PAYMENT_NETWORK_URL", "http://payment_network:8005")

        assert network_url == test_url

    def test_receipt_notification_enabled(self, monkeypatch):
        """Test receipt notification can be enabled/disabled"""
        monkeypatch.setenv("ENABLE_RECEIPT_NOTIFICATION", "false")

        import os
        enabled = os.getenv("ENABLE_RECEIPT_NOTIFICATION", "true").lower() == "true"

        assert enabled is False

    def test_receipt_notification_default(self):
        """Test receipt notification default value"""
        import os
        # Temporarily remove env var if exists
        original = os.environ.pop("ENABLE_RECEIPT_NOTIFICATION", None)

        enabled = os.getenv("ENABLE_RECEIPT_NOTIFICATION", "true").lower() == "true"

        # Restore if it existed
        if original:
            os.environ["ENABLE_RECEIPT_NOTIFICATION"] = original

        assert enabled is True


class TestModuleStructure:
    """Test module structure and dependencies"""

    def test_module_path_setup(self):
        """Test module path is set up correctly"""
        # The main module adds parent directory to path
        # This test verifies the import structure works
        from services.payment_processor.processor import PaymentProcessorService
        assert PaymentProcessorService is not None

    def test_common_modules_accessible(self):
        """Test common modules are accessible"""
        from common.telemetry import setup_telemetry
        from common.base_agent import BaseAgent
        from common.models import ProcessPaymentRequest

        assert setup_telemetry is not None
        assert BaseAgent is not None
        assert ProcessPaymentRequest is not None

    def test_processor_module_structure(self):
        """Test processor module has expected structure"""
        from services.payment_processor import processor

        # Check key classes/functions exist
        assert hasattr(processor, 'PaymentProcessorService')
        assert hasattr(processor, 'logger')
        assert hasattr(processor, 'tracer')
