# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a demonstration implementation of the **AP2 (Agent Payments Protocol)** - an open protocol developed by Google and 60+ organizations for AI agents to safely execute payments. This codebase implements the full 6-entity architecture with cryptographic signatures, risk assessment, and an interactive Streamlit demo.

## Key Commands

### Running the Application

```bash
# Interactive Streamlit demo (recommended)
streamlit run ap2_demo_app.py

# Individual component demos
python secure_shopping_agent.py
python secure_merchant_agent.py
python merchant.py
python payment_processor.py
python risk_assessment.py
```

### Installing Dependencies

```bash
pip install -r requirements.txt

# Additional for Streamlit demo
pip install streamlit reportlab
```

## Architecture Overview

### 6-Entity Architecture

The codebase implements the complete AP2 specification with proper entity separation:

1. **User** - End user making purchases
2. **Shopping Agent** (`secure_shopping_agent.py`) - User's purchasing assistant
3. **Merchant Agent** (`secure_merchant_agent.py`) - Creates Cart Mandates (unsigned)
4. **Merchant** (`merchant.py`) - Validates and signs Cart Mandates (separate from Agent)
5. **Credential Provider** (`credential_provider.py`) - Manages payment methods
6. **Payment Processor** (`payment_processor.py`) - Executes transactions

**Critical Distinction:** Merchant Agent and Merchant are separate entities. The Agent creates Cart Mandates WITHOUT signing them. Only the actual Merchant entity validates and adds Merchant signatures.

### Three Mandate Types

All mandates are defined in `ap2_types.py`:

1. **Intent Mandate** - User's purchase authorization with constraints (max amount, brands, categories)
2. **Cart Mandate** - Specific cart contents requiring both Merchant signature AND User signature
3. **Payment Mandate** - Payment network submission with risk assessment

### Cryptographic Infrastructure

Located in `ap2_crypto.py`:

- **KeyManager**: ECDSA key pair generation, encrypted storage (AES-256-CBC), PEM serialization
- **SignatureManager**: ECDSA-SHA256 signatures for all mandates
- Keys are stored in `./keys/` directory with encrypted private keys

**Key Pair Management Pattern:**
```python
# All entities follow this pattern
key_manager = KeyManager()
try:
    private_key = key_manager.load_private_key_encrypted(entity_id, passphrase)
except:
    private_key, public_key = key_manager.generate_key_pair(entity_id)
    key_manager.save_private_key_encrypted(entity_id, private_key, passphrase)
```

### Risk Assessment Engine

`risk_assessment.py` implements production-grade risk evaluation:

- **8 Risk Factors**: amount, constraints, agent involvement, transaction type (CNP/CP), payment method, pattern analysis, shipping, temporal
- **Fraud Indicators**: Returns specific flags (e.g., `high_transaction_amount`, `card_not_present_transaction`)
- **Risk Score**: 0-100 weighted calculation with recommendations (approve/review/decline)
- **Transaction History**: Tracks patterns to detect card testing and unusual behavior

The risk engine is integrated into Shopping Agent's `create_payment_mandate()` method and populates `risk_score` and `fraud_indicators` fields.

## Critical Implementation Details

### Signature Flow for Cart Mandates

This is the most important flow to understand:

1. **Merchant Agent** creates Cart Mandate (line ~476 in `secure_merchant_agent.py`)
   - NO signature added
   - Returns unsigned Cart Mandate

2. **Merchant** validates and signs (line ~84 in `merchant.py`)
   - Validates merchant_id match, inventory, pricing
   - Adds `merchant_signature` using `sign_cart_mandate()`

3. **User** approves and signs (line ~229 in `secure_shopping_agent.py`)
   - Shopping Agent's `select_and_sign_cart()` method
   - Adds `user_signature`

4. **Shopping Agent** verifies both signatures before payment

### SignatureManager Method Signature

**CRITICAL:** The argument order for `sign_data()` in `ap2_crypto.py`:

```python
def sign_data(self, data: Any, key_id: str, algorithm: str = 'ECDSA') -> Signature:
    # First arg: data to sign (dict/string)
    # Second arg: key_id for private key lookup
```

Always call as: `sign_data(cart_data, merchant_id)` NOT `sign_data(merchant_id, cart_data)`

### Streamlit App State Management

`ap2_demo_app.py` uses session state for all entities:

- `st.session_state.shopping_agent` - Shopping Agent instance
- `st.session_state.merchant_agent` - Merchant Agent instance
- `st.session_state.merchant` - Merchant instance (separate!)
- `st.session_state.payment_processor` - Payment Processor instance
- `st.session_state.credential_provider` - Credential Provider instance

**UI Pattern:** Use `st.status()` for multi-step processes, NOT nested `st.expander()` (causes errors). Use `st.caption()` for inline details.

## File Organization

### Core Protocol Files

- `ap2_types.py` - All dataclass definitions (Mandates, Amounts, Signatures, etc.)
- `ap2_crypto.py` - Cryptographic operations (ECDSA, AES-256-CBC)

### Entity Implementations

- `secure_shopping_agent.py` - User's agent (creates Intent/Payment Mandates, processes payments)
- `secure_merchant_agent.py` - Merchant's agent (searches products, creates UNSIGNED Cart Mandates)
- `merchant.py` - Actual merchant (validates and SIGNS Cart Mandates)
- `credential_provider.py` - Payment method storage and tokenization
- `payment_processor.py` - Transaction authorization, capture, refund

### Supporting Modules

- `risk_assessment.py` - Fraud detection and risk scoring
- `receipt_generator.py` - PDF receipt generation with reportlab
- `ap2_demo_app.py` - Interactive Streamlit demo (main entry point)

## Common Development Patterns

### Adding New Risk Factors

Edit `risk_assessment.py`:
1. Add assessment method (e.g., `_assess_new_factor()`)
2. Call from `assess_payment_mandate()`
3. Add to `risk_factors` dict with weight
4. Update `_calculate_total_risk_score()` weights dict

### Modifying Mandate Structure

1. Update dataclass in `ap2_types.py`
2. Update signature data dict in relevant entity's `sign_*_mandate()` method
3. Update corresponding `verify_*_signature()` method
4. Regenerate keys (delete `./keys/` directory to reset)

### Testing Signature Verification

Each entity module has a `demo_*()` function at the bottom that can be run standalone:

```bash
python merchant.py  # Tests Merchant signature flow
python payment_processor.py  # Tests payment processing
```

## Data Flow Summary

```
User Input → Intent Mandate (User signs)
  ↓
Shopping Agent validates → searches via Merchant Agent
  ↓
Merchant Agent creates Cart Mandate (unsigned)
  ↓
Merchant validates & signs Cart Mandate
  ↓
User reviews & signs Cart Mandate
  ↓
Shopping Agent creates Payment Mandate (with risk assessment)
  ↓
Payment Processor authorizes & captures
  ↓
Receipt generated → Transaction complete
```

## Important Constraints

- **Python 3.10+** required (uses match statements and new type hints)
- **Streamlit** for demo UI (not in requirements.txt, install separately)
- **Keys directory** (`./keys/`) auto-created, stores encrypted private keys
- **Risk assessment** requires both Cart Mandate and Intent Mandate context
- **All timestamps** use ISO 8601 format with 'Z' suffix (UTC)

## References

- Official AP2 spec: https://ap2-protocol.org/specification/
- GitHub: https://github.com/google-agentic-commerce/AP2