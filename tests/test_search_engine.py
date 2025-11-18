"""
Tests for Search Engine (Meilisearch integration)

Tests cover:
- MeilisearchClient initialization
- Index creation and configuration
- Document operations (add, update, delete)
- Search functionality
- Error handling
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from common.search_engine import MeilisearchClient


class TestMeilisearchClientInitialization:
    """Test MeilisearchClient initialization"""

    def test_initialization_with_defaults(self):
        """Test client initialization with default values"""
        client = MeilisearchClient()

        assert client.url == "http://meilisearch:7700"
        assert client.master_key == "masterKey123"
        assert client.index_name == "products"

    def test_initialization_with_custom_values(self):
        """Test client initialization with custom values"""
        client = MeilisearchClient(
            url="http://custom:8080",
            master_key="customKey"
        )

        assert client.url == "http://custom:8080"
        assert client.master_key == "customKey"
        assert client.index_name == "products"

    def test_initialization_with_env_vars(self, monkeypatch):
        """Test client initialization with environment variables"""
        monkeypatch.setenv("MEILISEARCH_URL", "http://env:9000")
        monkeypatch.setenv("MEILISEARCH_MASTER_KEY", "envKey")

        client = MeilisearchClient()

        assert client.url == "http://env:9000"
        assert client.master_key == "envKey"


class TestMeilisearchIndexOperations:
    """Test Meilisearch index operations"""

    @pytest.mark.asyncio
    async def test_create_index_success(self):
        """Test successful index creation"""
        client = MeilisearchClient()

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "uid": "products",
            "taskUid": 1
        }

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            result = await client.create_index("id")

            assert result["uid"] == "products"
            assert "taskUid" in result
            mock_client_instance.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_index_already_exists(self):
        """Test index creation when it already exists"""
        client = MeilisearchClient()

        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {
            "uid": "products",
            "taskUid": 2
        }

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            result = await client.create_index()

            assert result["uid"] == "products"

    @pytest.mark.asyncio
    async def test_create_index_error(self):
        """Test index creation error handling"""
        client = MeilisearchClient()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Error", request=MagicMock(), response=mock_response
        )

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            with pytest.raises(httpx.HTTPStatusError):
                await client.create_index()

    @pytest.mark.asyncio
    async def test_configure_index_success(self):
        """Test successful index configuration"""
        client = MeilisearchClient()

        mock_response = MagicMock()
        mock_response.status_code = 202

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.patch = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            await client.configure_index()

            mock_client_instance.patch.assert_called_once()
            call_args = mock_client_instance.patch.call_args

            # Verify settings structure
            settings = call_args[1]["json"]
            assert "searchableAttributes" in settings
            assert "filterableAttributes" in settings
            assert "sortableAttributes" in settings
            assert "name" in settings["searchableAttributes"]

    @pytest.mark.asyncio
    async def test_configure_index_error(self):
        """Test index configuration error handling"""
        client = MeilisearchClient()

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Error", request=MagicMock(), response=mock_response
        )

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.patch = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            with pytest.raises(httpx.HTTPStatusError):
                await client.configure_index()

    @pytest.mark.asyncio
    async def test_clear_index_success(self):
        """Test clearing index"""
        client = MeilisearchClient()

        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {"taskUid": 10}

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.delete = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            result = await client.clear_index()

            assert "taskUid" in result
            mock_client_instance.delete.assert_called_once()


class TestMeilisearchDocumentOperations:
    """Test Meilisearch document operations"""

    @pytest.mark.asyncio
    async def test_add_documents_success(self):
        """Test adding documents successfully"""
        client = MeilisearchClient()

        documents = [
            {
                "id": "prod_001",
                "name": "Running Shoes",
                "description": "Comfortable running shoes",
                "price_jpy": 8000
            },
            {
                "id": "prod_002",
                "name": "Basketball Shoes",
                "description": "High-top basketball shoes",
                "price_jpy": 12000
            }
        ]

        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {"taskUid": 5}

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            result = await client.add_documents(documents)

            assert result["taskUid"] == 5
            mock_client_instance.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_documents_empty_list(self):
        """Test adding empty document list"""
        client = MeilisearchClient()

        result = await client.add_documents([])

        assert result == {}

    @pytest.mark.asyncio
    async def test_add_documents_error(self):
        """Test document addition error handling"""
        client = MeilisearchClient()

        documents = [{"id": "prod_001", "name": "Test"}]

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Invalid document"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Error", request=MagicMock(), response=mock_response
        )

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            with pytest.raises(httpx.HTTPStatusError):
                await client.add_documents(documents)

    @pytest.mark.asyncio
    async def test_update_document_success(self):
        """Test updating a document"""
        client = MeilisearchClient()

        document = {
            "id": "prod_001",
            "name": "Updated Running Shoes",
            "price_jpy": 9000
        }

        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {"taskUid": 7}

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            result = await client.update_document(document)

            assert result["taskUid"] == 7

    @pytest.mark.asyncio
    async def test_delete_document_success(self):
        """Test deleting a document"""
        client = MeilisearchClient()

        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {"taskUid": 8}

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.delete = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            result = await client.delete_document("prod_001")

            assert result["taskUid"] == 8
            mock_client_instance.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_document_error(self):
        """Test document deletion error handling"""
        client = MeilisearchClient()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Document not found"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Error", request=MagicMock(), response=mock_response
        )

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.delete = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            with pytest.raises(httpx.HTTPStatusError):
                await client.delete_document("prod_999")


class TestMeilisearchSearch:
    """Test Meilisearch search functionality"""

    @pytest.mark.asyncio
    async def test_search_success(self):
        """Test successful search"""
        client = MeilisearchClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "hits": [
                {"id": "prod_001"},
                {"id": "prod_002"},
                {"id": "prod_003"}
            ],
            "total": 3
        }

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            result = await client.search("running shoes")

            assert len(result) == 3
            assert result[0] == "prod_001"
            assert result[1] == "prod_002"
            assert result[2] == "prod_003"

    @pytest.mark.asyncio
    async def test_search_with_filters(self):
        """Test search with filters"""
        client = MeilisearchClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "hits": [{"id": "prod_001"}],
            "total": 1
        }

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            result = await client.search(
                "shoes",
                limit=10,
                filters="category = 'sports'"
            )

            assert len(result) == 1
            call_args = mock_client_instance.post.call_args
            search_params = call_args[1]["json"]
            assert search_params["filter"] == "category = 'sports'"
            assert search_params["limit"] == 10

    @pytest.mark.asyncio
    async def test_search_no_results(self):
        """Test search with no results"""
        client = MeilisearchClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "hits": [],
            "total": 0
        }

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            result = await client.search("nonexistent product")

            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_search_error(self):
        """Test search error handling"""
        client = MeilisearchClient()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            result = await client.search("test")

            # Should return empty list on error
            assert result == []

    @pytest.mark.asyncio
    async def test_search_custom_limit(self):
        """Test search with custom limit"""
        client = MeilisearchClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "hits": [{"id": f"prod_{i:03d}"} for i in range(5)],
            "total": 5
        }

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            result = await client.search("shoes", limit=5)

            assert len(result) == 5
            call_args = mock_client_instance.post.call_args
            assert call_args[1]["json"]["limit"] == 5
