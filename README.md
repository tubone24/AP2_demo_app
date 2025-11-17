# AP2 Demo Application

AP2 Protocol (Agent Payments Protocol) implementation with microservices architecture. Built with FastAPI, Docker Compose, Next.js, LangGraph, MCP, Meilisearch, Redis, WebAuthn, and OpenTelemetry.

![demo](./docs/images/demo.gif)

## Overview

This application is a implementation of the AP2 (Agent Payments Protocol) specification using a microservices architecture. It features **15 services** (7 Backend + 2 MCP + 1 Frontend + 1 Redis + 1 Meilisearch + 1 Jaeger + 1 Payment Network + 1 Init Services) that work together to provide:

- **LangGraph AI Conversations** - Intelligent dialogue management with OpenAI GPT-4
- **MCP (Model Context Protocol) Integration** - Tool orchestration for AI agents
- **Full-text Search** - Product search powered by Meilisearch
- **KV Store** - Session and token management with Redis
- **WebAuthn/Passkey Authentication** - Secure passwordless authentication
- **OpenTelemetry Distributed Tracing** - Complete observability with Jaeger
- **AP2 Mandate Chain** - Intent → Cart → Payment mandate verification
- **Payment Network Integration** - Complete agent token lifecycle

## Architecture Diagram

```mermaid
graph TB
    subgraph "Frontend (Next.js)"
        UI[Chat UI<br/>Merchant Dashboard<br/>Port 3000]
    end

    subgraph "Backend Services"
        SA[Shopping Agent<br/>Port 8000<br/>LangGraph Integration]
        SA_MCP[Shopping Agent MCP<br/>Port 8010<br/>6 MCP Tools]
        MA[Merchant Agent<br/>Port 8001<br/>LangGraph Integration]
        MA_MCP[Merchant Agent MCP<br/>Port 8011<br/>3 MCP Tools]
        M[Merchant<br/>Port 8002<br/>CartMandate Signing]
        CP[Credential Provider<br/>Port 8003<br/>WebAuthn Verification]
        CP2[Credential Provider 2<br/>Port 8006<br/>Multi-CP Support]
        PP[Payment Processor<br/>Port 8004<br/>Payment Processing]
        PN[Payment Network<br/>Port 8005<br/>Agent Token Issuance]
    end

    subgraph "Infrastructure Services"
        REDIS[(Redis<br/>Port 6379<br/>KV Store & Sessions)]
        MEILI[(Meilisearch<br/>Port 7700<br/>Full-text Search)]
        JAEGER[Jaeger<br/>Port 16686<br/>Distributed Tracing]
    end

    subgraph "External Services"
        DMR[DMR/OpenAI<br/>LLM Endpoint]
        LF[Langfuse<br/>LLM Observability]
    end

    subgraph "Data Layer"
        DB[(SQLite Databases<br/>Per-Service Storage)]
        Keys[Encrypted Keys<br/>Ed25519 + ECDSA]
    end

    UI -->|SSE Chat| SA
    UI -->|WebAuthn| CP
    UI -->|Product CRUD| M

    SA -->|LangGraph Tools| SA_MCP
    SA_MCP -->|build_intent<br/>request_carts<br/>select_cart<br/>assess_risk<br/>build_payment<br/>execute_payment| SA

    MA -->|LangGraph Tools| MA_MCP
    MA_MCP -->|search_products<br/>check_inventory<br/>build_cart_mandates| MA
    MA_MCP -->|Full-text Search| MEILI

    SA -->|A2A Message| MA
    MA -->|A2A Message| M
    M -->|A2A Message| SA
    SA -->|A2A Message| PP
    SA -->|A2A Message| CP
    CP -->|POST /network/tokenize| PN
    PP -->|POST /credentials/verify| CP
    PP -->|POST /network/charge| PN

    CP -->|Token/Session<br/>TTL: 15min/10min| REDIS
    PN -->|Agent Token<br/>TTL: 1hour| REDIS

    SA & MA & M & CP & PP -->|Read/Write| DB
    SA & MA & M & CP & PP -->|Load Keys| Keys
    SA & MA & M & CP & PP -.->|Trace| JAEGER

    SA -.->|LLM Query| DMR
    MA -.->|LLM Query| DMR
    SA -.->|Langfuse Trace| LF
    MA -.->|Langfuse Trace| LF

    style UI fill:#e1f5ff
    style SA fill:#fff4e6
    style SA_MCP fill:#e1bee7
    style MA fill:#fff4e6
    style MA_MCP fill:#e1bee7
    style M fill:#fff4e6
    style CP fill:#e8f5e9
    style CP2 fill:#e8f5e9
    style PP fill:#e8f5e9
    style PN fill:#b2dfdb
    style REDIS fill:#fce4ec
    style MEILI fill:#ffccbc
    style JAEGER fill:#c8e6c9
```

### Services Overview

| Service | Port | Type | Role | Technology Stack |
|---------|------|------|------|-----------------|
| **Frontend** | 3000 | UI | User Interface | Next.js 15, TypeScript, shadcn/ui |
| **Shopping Agent** | 8000 | Backend | User's AI Agent | FastAPI, LangGraph, A2A Protocol |
| **Shopping Agent MCP** | 8010 | MCP | MCP Tool Server (×6) | FastAPI, MCP Server |
| **Merchant Agent** | 8001 | Backend | Product Search & Cart Creation | FastAPI, LangGraph, A2A Protocol |
| **Merchant Agent MCP** | 8011 | MCP | MCP Tool Server (×3) | FastAPI, MCP Server, Meilisearch |
| **Merchant** | 8002 | Backend | Cart Signing & Inventory | FastAPI, CartMandate Signing |
| **Credential Provider** | 8003 | Backend | WebAuthn & Token Issuance | FastAPI, WebAuthn, Redis |
| **Credential Provider 2** | 8006 | Backend | Multi-CP Support | FastAPI, WebAuthn, Redis |
| **Payment Processor** | 8004 | Backend | Payment Processing | FastAPI, Receipt Generation |
| **Payment Network** | 8005 | Backend | Agent Token Lifecycle | FastAPI, Token Issuance & Verification |
| **Redis** | 6379 | Infra | KV Store & Sessions | Redis 7-alpine, TTL Management |
| **Meilisearch** | 7700 | Infra | Full-text Search Engine | Meilisearch v1.11 |
| **Jaeger** | 16686 | Infra | Distributed Tracing | Jaeger All-in-One, OpenTelemetry |

### AP2-Compliant Entities

| Entity | Service | Port | Role | AP2 Compliance |
|--------|---------|------|------|---------------|
| **User** | Frontend | 3000 | End User | ✅ WebAuthn Signing (SD-JWT+KB) |
| **Shopping Agent** | Shopping Agent | 8000 | User's Agent | ✅ IntentMandate/PaymentMandate |
| **Merchant Agent** | Merchant Agent | 8001 | Product Search | ✅ A2A Protocol |
| **Merchant** | Merchant | 8002 | Seller | ✅ CartMandate Signing |
| **Credential Provider** | Credential Provider | 8003 | Authentication | ✅ WebAuthn Verification |
| **Payment Processor** | Payment Processor | 8004 | Payment Processing | ✅ Mandate Verification |
| **Payment Network** | Payment Network | 8005 | Token Issuance | ✅ Agent Token Lifecycle |

### Sequence Flow Key Points

#### Phase 1: LangGraph Dialogue Flow
- **Intent Collection**: Shopping Agent uses LangGraph to gradually collect required information
- **State Management**: `extract_info` → `check_completeness` → `generate_question`
- **Required Fields**: `intent`, `max_amount`

#### Phase 2-4: Mandate Chain Creation
- **IntentMandate**: User signs with WebAuthn (SD-JWT+KB format)
- **CartMandate**: Merchant signs with ECDSA + JWT, User signs with WebAuthn
- **Challenge Management**: Redis-backed with 60-second TTL (replay attack prevention)

#### Phase 5: AP2 Payment Flow (Steps 17-29)

**Step 17-19: Tokenization**
- User selects payment method
- Credential Provider tokenizes payment method
- Token stored in Redis (TTL: 15 minutes)

**Step 20-22: PaymentMandate Creation**
- Shopping Agent creates PaymentMandate
- Risk assessment performed (amount, method, user history)

**Step 23: Agent Token Issuance**
- User signs PaymentMandate with WebAuthn
- Credential Provider requests Agent Token from Payment Network
- Payment Network issues Agent Token (stored in Redis, TTL: 1 hour)
- Agent Token associated with payment_method_token

**Step 26-27: Credential Verification**
- Payment Processor verifies credential token with Credential Provider
- Credential Provider returns agent_token from token_data

**Step 28: Payment Execution**
- Payment Processor calls Payment Network with agent_token
- Payment Network verifies agent_token
- Payment Network executes charge (stub implementation)
- Returns network_transaction_id and authorization_code

**Step 29: Receipt Generation**
- Payment Processor generates PDF receipt
- Receipt URL sent to Credential Provider
- User receives receipt download link

### Security Features

- **Cryptographic Signatures**: All A2A messages signed with Ed25519/ECDSA
- **WebAuthn Authentication**: Passwordless authentication with Passkey
- **SD-JWT+KB**: Selective Disclosure JWT with Key Binding for user authorization
- **Challenge-Response**: Redis-backed challenges with TTL (replay attack prevention)
- **Token Lifecycle**: Proper TTL management (payment_method_token: 15min, agent_token: 1hour)
- **Mandate Chain Verification**: Complete validation of Intent → Cart → Payment chain

## Getting Started

### Prerequisites

- Docker & Docker Compose
- OpenAI API Key (for LangGraph) or DMR endpoint

### Quick Start

#### 1. Environment Setup

```bash
cd /path/to/ap2/

# Create .env file
cat > .env << 'EOF'
# OpenAI API (Required for LangGraph)
OPENAI_API_KEY=sk-proj-your-api-key-here

# DMR Endpoint (alternative to OpenAI)
DMR_API_URL=http://host.docker.internal:12434/engines/llama.cpp/v1
DMR_MODEL=ai/qwen3
DMR_API_KEY=none

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=text

# Langfuse (Optional)
LANGFUSE_ENABLED=false
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

# OpenTelemetry
OTEL_ENABLED=true
EOF
```

**Note**: If you're using DMR (alternative to OpenAI), you need to set up DMR before starting the services. See [DMR Setup](#dmr-setup) below.

#### 2. DMR Setup (Optional)

If you want to use DMR instead of OpenAI for LangGraph's LLM inference, follow these steps:

**What is DMR?**
- DMR is a local LLM inference engine that provides an OpenAI-compatible API
- Useful for development/testing without OpenAI API costs
- Supports various models (Qwen, Llama, etc.)

**Installation**:

```bash
# 1. Install DMR (example using Homebrew on macOS)
brew install dmr

# Or download from DMR releases
# https://github.com/your-dmr-repo/releases

# 2. Download and configure a model (e.g., Qwen3)
dmr pull ai/qwen3

# 3. Start DMR server
dmr serve --port 12434

# 4. Verify DMR is running
curl http://localhost:12434/v1/models
```

**Configuration**:

In your `.env` file, set:
```bash
DMR_API_URL=http://host.docker.internal:12434/engines/llama.cpp/v1
DMR_MODEL=ai/qwen3
DMR_API_KEY=none
```

**Note**: `host.docker.internal` allows Docker containers to access the host machine's localhost.

**Alternative: Use OpenAI**

If you don't want to set up DMR, simply provide your OpenAI API key:
```bash
OPENAI_API_KEY=sk-proj-your-api-key-here
```

The Shopping Agent will automatically use OpenAI if `OPENAI_API_KEY` is set.

#### 3. Start All Services

```bash
# Build and start all services
docker compose up --build

# Or run in background
docker compose up --build -d
```

This will start all 15 services:
- **7 Backend Services**: Shopping Agent, Merchant Agent, Merchant, Credential Provider (×2), Payment Processor, Payment Network
- **2 MCP Services**: Shopping Agent MCP, Merchant Agent MCP
- **1 Frontend**: Next.js
- **3 Infrastructure Services**: Redis, Meilisearch, Jaeger
- **2 Init Services**: init-keys, init-seeds (run once at startup)

#### 4. Verify Services

```bash
# Check service health
curl http://localhost:8000/health  # Shopping Agent
curl http://localhost:8001/health  # Merchant Agent
curl http://localhost:8002/health  # Merchant
curl http://localhost:8003/health  # Credential Provider
curl http://localhost:8004/health  # Payment Processor
curl http://localhost:8005/health  # Payment Network

# Access web interfaces
open http://localhost:3000          # Frontend
open http://localhost:3000/chat     # Chat UI (main demo)
open http://localhost:3000/merchant # Merchant Dashboard
open http://localhost:16686         # Jaeger UI (tracing)
open http://localhost:7700          # Meilisearch UI
```

#### 5. Demo Flow

1. **Passkey Registration** - Register at `/chat` on first visit
2. **Product Search** - Enter "I want cute merchandise"
3. **Intent Signing** - Enter max budget and sign with Passkey
4. **Cart Selection** - LLM proposes carts, select one
5. **Cart Signing** - Review cart contents and sign with Passkey
6. **Payment** - Select payment method and sign
7. **Receipt** - Download PDF receipt after payment completion

#### 6. View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f shopping_agent
docker compose logs -f payment_processor
docker compose logs -f payment_network

# Filter for Payment Network integration
docker compose logs -f payment_processor payment_network credential_provider | grep -E "(agent_token|charge|tokenize)"
```

#### 6. Stop Services

```bash
# Stop (keep containers)
docker compose stop

# Stop and remove containers
docker compose down

# Remove everything including volumes
docker compose down -v
```

### Development Setup (Local Execution)

For local development without Docker:

```bash
# Install Python dependencies
cd /path/to/ap2/
pip install -e .

# Frontend dependencies
cd frontend/
npm install

# Set environment variables
export OPENAI_API_KEY=sk-proj-your-api-key-here
export LOG_LEVEL=INFO

# Start services in separate terminals
# Terminal 1: Shopping Agent
cd services/shopping_agent && python main.py

# Terminal 2: Merchant Agent
cd services/merchant_agent && python main.py

# Terminal 3: Merchant
cd services/merchant && python main.py

# Terminal 4: Credential Provider
cd services/credential_provider && python main.py

# Terminal 5: Payment Processor
cd services/payment_processor && python main.py

# Terminal 6: Payment Network
cd services/payment_network && python main.py

# Terminal 7: Frontend
cd frontend && npm run dev
```

## Testing

This project includes comprehensive test coverage for core functionality.

### Running Tests

```bash
# Install test dependencies
uv pip install --system pytest pytest-asyncio

# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_crypto.py -v

# Run specific test class
pytest tests/test_database.py::TestProductCRUD -v

# Run with coverage (requires pytest-cov)
pytest tests/ --cov=common --cov=services --cov-report=html
```

### Test Structure

```
tests/
├── __init__.py
├── conftest.py                        # Pytest fixtures and configuration
├── test_crypto.py                     # Cryptography tests (21 tests)
├── test_database.py                   # Database CRUD tests (28 tests)
├── test_shopping_agent_api.py         # Shopping Agent API tests (14 tests)
└── test_payment_processor_api.py      # Payment Processor API tests (13 tests)
```

### Test Coverage

- **Cryptography Module** (`common/crypto.py`):
  - JSON canonicalization and mandate hashing
  - ECDSA and Ed25519 key generation/management
  - Signature creation and verification
  - Secure storage encryption/decryption
  - WebAuthn challenge management
  - Device attestation

- **Database Module** (`common/database.py`):
  - Product, User, Mandate CRUD operations
  - Transaction and session management
  - Passkey credential storage
  - Payment method and receipt management

- **API Modules**:
  - Shopping Agent authentication and mandate structures
  - Payment Processor validation and tokenization
  - A2A message structures
  - Risk assessment logic

### Continuous Integration

Tests are automatically run on every push and pull request via GitHub Actions:

```yaml
# .github/workflows/test.yml
# Tests run on Python 3.10 and 3.11
```

View test results in the Actions tab of the GitHub repository.

## Technology Stack

### Backend
- **FastAPI** 0.115.0 - High-performance web framework
- **SQLAlchemy** 2.0.35 - ORM
- **aiosqlite** 0.20.0 - Async SQLite
- **cryptography** 43.0.0 - ECDSA signing & AES-256-CBC encryption
- **fido2** 1.1.3 - WebAuthn verification
- **sse-starlette** 2.1.0 - Server-Sent Events
- **httpx** 0.27.0 - Async HTTP client
- **LangGraph** - LLM conversation flow management
- **LangChain** 0.3.0+ - LLM integration (OpenAI-compatible API)
- **Langfuse** 2.0.0+ - LLM Observability
- **ReportLab** - PDF generation
- **PyJWT** - JWT signing
- **redis** 5.0.0+ - Redis KV client

### Frontend
- **Next.js** 15.1.4 (App Router)
- **React** 19.0.0
- **TypeScript** 5.x
- **TailwindCSS** 3.4.1
- **shadcn/ui** - UI component library
- **WebAuthn API** - Passkey signing

### Infrastructure
- **Docker** + **Docker Compose** - Container orchestration
- **SQLite** - Development database
- **Redis** 7-alpine - KV store & session management
- **Meilisearch** v1.11 - Full-text search engine
- **Jaeger** - Distributed tracing (OpenTelemetry)

## Project Structure

```
ap2/
├── common/                      # Shared modules
│   ├── models.py                # Pydantic models (A2A messages, API types)
│   ├── a2a_handler.py           # A2A message handling
│   ├── base_agent.py            # Base class for all agents
│   ├── database.py              # SQLAlchemy models + CRUD
│   ├── redis_client.py          # Redis KV client (TokenStore, SessionStore)
│   ├── crypto.py                # Ed25519/ECDSA signing, AES-256 encryption
│   ├── logger.py                # Unified logging (JSON/text)
│   ├── user_authorization.py    # SD-JWT+KB verification
│   ├── risk_assessment.py       # Risk assessment engine
│   └── receipt_generator.py    # PDF receipt generation
│
├── services/                    # Microservices
│   ├── shopping_agent/          # Shopping Agent (Port 8000)
│   ├── shopping_agent_mcp/      # Shopping Agent MCP (Port 8010)
│   ├── merchant_agent/          # Merchant Agent (Port 8001)
│   ├── merchant_agent_mcp/      # Merchant Agent MCP (Port 8011)
│   ├── merchant/                # Merchant (Port 8002)
│   ├── credential_provider/     # Credential Provider (Port 8003)
│   ├── payment_processor/       # Payment Processor (Port 8004)
│   └── payment_network/         # Payment Network (Port 8005)
│
├── frontend/                    # Next.js frontend (Port 3000)
│   ├── app/                     # App Router
│   │   ├── page.tsx             # Home page
│   │   ├── chat/page.tsx        # Chat UI (SSE/Streaming)
│   │   └── merchant/page.tsx    # Merchant Dashboard
│   ├── components/              # React components
│   └── lib/                     # Utilities & types
│
├── scripts/                     # Utility scripts
│   ├── init_keys.py             # Key pair initialization
│   └── init_seeds.py            # Seed data injection
│
├── data/                        # Persistent data (Docker Volume)
│   ├── *.db                     # SQLite databases (per service)
│   ├── receipts/                # PDF receipts
│   └── did_documents/           # DID Documents
│
├── keys/                        # Encrypted keys (Docker Volume)
│   └── *_private.pem            # Ed25519/ECDSA private keys (AES-256)
│
├── docker-compose.yml           # Service orchestration
├── pyproject.toml               # Python dependencies (uv)
└── README.md                    # This file
```

## API Endpoints

### Common Endpoints (All Services)

All services expose these endpoints:
- `GET /` - Health check (returns agent_id, agent_name, status, version)
- `GET /health` - Health check (for Docker)
- `POST /a2a/message` - A2A message reception (auto-implemented by BaseAgent)

### Shopping Agent (Port 8000)

**User Interaction:**
- `POST /chat/stream` - Chat dialogue (SSE Streaming)
- `POST /create-intent` - Create IntentMandate
- `POST /create-payment` - Create PaymentMandate
- `GET /transactions/{transaction_id}` - Get transaction

### Merchant Agent (Port 8001)

**Product Search & Cart Creation:**
- `GET /products?query=...&limit=10` - Product search
- `POST /create-cart` - Create CartMandate (unsigned)

### Merchant (Port 8002)

**Cart Signing & Inventory:**
- `POST /sign/cart` - Sign CartMandate
- `GET /inventory/{sku}` - Check inventory
- `GET /products` - List products
- `POST /products` - Add product

### Credential Provider (Port 8003)

**WebAuthn & Token Issuance:**
- `POST /attestations/verify` - Verify WebAuthn attestation
- `GET /payment-methods?user_id=...` - List payment methods
- `POST /payment-methods` - Add payment method
- `POST /payment-methods/tokenize` - Tokenize payment method
- `POST /credentials/verify` - Verify credential token (returns agent_token)
- `GET /webauthn/options` - Get WebAuthn challenge

### Payment Processor (Port 8004)

**Payment Processing:**
- `POST /process` - Execute payment
- `GET /transactions/{transaction_id}` - Get transaction
- `POST /refund` - Process refund
- `GET /receipts/{transaction_id}.pdf` - Download PDF receipt (JWT-authenticated)

### Payment Network (Port 8005)

**Agent Token Lifecycle:**
- `POST /network/tokenize` - Issue Agent Token (AP2 Step 23)
- `POST /network/verify-token` - Verify Agent Token
- `POST /network/charge` - Execute payment charge (AP2 Step 28)
- `GET /network/info` - Get network information

## AP2 Specification Compliance

This application fully implements the AP2 (Agent Payments Protocol) v0.2 specification:

### Mandate Chain

1. **IntentMandate** - User's purchase intent (max_amount, categories)
2. **CartMandate** - Specific cart contents (Merchant signature + User signature)
3. **PaymentMandate** - Payment information (payment method, risk score)

### Payment Flow (AP2 Steps 17-29)

- **Step 17-19**: Payment method selection & tokenization
- **Step 20-22**: PaymentMandate creation with risk assessment
- **Step 23**: Agent Token issuance from Payment Network
- **Step 24-25**: Payment execution request
- **Step 26-27**: Credential verification & agent token retrieval
- **Step 28**: Payment charge via Payment Network
- **Step 29**: Receipt generation & notification

### Security Features

- **SD-JWT+KB**: Selective Disclosure JWT with Key Binding for user_authorization
- **Merchant Authorization**: ECDSA + JWT signatures for CartMandate
- **WebAuthn**: FIDO2-based passwordless authentication
- **Challenge-Response**: Replay attack prevention with Redis TTL
- **Token Lifecycle**: Proper TTL management for all tokens

## References

- [AP2 Official Specification](https://ap2-protocol.org/specification/)
- [Google AP2 Samples](https://github.com/google-agentic-commerce/AP2)
- [W3C Payment Request API](https://www.w3.org/TR/payment-request/)
- [WebAuthn Specification](https://www.w3.org/TR/webauthn/)

## Troubleshooting

### Database Errors

```bash
# Reset databases
rm -rf data/*.db

# Reinitialize
docker compose up init-seeds
```

### Key Generation Errors

```bash
# Reset keys
rm -rf keys/*

# Services will auto-generate keys on restart
docker compose restart
```

### Port Conflicts

```bash
# Check port usage
lsof -ti:8000 | xargs kill -9  # Kill process on port 8000
```

### Redis Connection Errors

```bash
# Restart Redis
docker compose restart redis

# Check Redis health
docker compose exec redis redis-cli ping
```

