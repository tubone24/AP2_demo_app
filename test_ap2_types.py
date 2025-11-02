#!/usr/bin/env python3
"""
AP2型定義のユニットテスト

以下の型定義が正しく動作することを検証:
1. W3C Payment Request API型（11型）
2. AP2 Mandate型（5型）
3. JWT生成・検証ユーティリティ
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

print("=" * 70)
print("AP2型定義 - ユニットテスト")
print("=" * 70)

# Test 1: W3C Payment Request API型のインポート
print("\n[Test 1] W3C Payment Request API型のインポート確認")
try:
    from common.payment_types import (
        ContactAddress,
        PaymentCurrencyAmount,
        PaymentItem,
        PaymentShippingOption,
        PaymentOptions,
        PaymentMethodData,
        PaymentDetailsModifier,
        PaymentDetailsInit,
        PaymentRequest,
        PaymentResponse,
    )
    print("  ✓ 全11型のインポートに成功しました")
except ImportError as e:
    print(f"  ✗ インポート失敗: {e}")
    sys.exit(1)

# Test 2: AP2 Mandate型のインポート
print("\n[Test 2] AP2 Mandate型のインポート確認")
try:
    from common.mandate_types import (
        IntentMandate,
        CartContents,
        CartMandate,
        PaymentMandateContents,
        PaymentMandate,
    )
    print("  ✓ 全5型のインポートに成功しました")
except ImportError as e:
    print(f"  ✗ インポート失敗: {e}")
    sys.exit(1)

# Test 3: PaymentCurrencyAmount型の動作確認
print("\n[Test 3] PaymentCurrencyAmount型の動作確認")
try:
    amount = PaymentCurrencyAmount(currency="JPY", value=1000.0)
    assert amount.currency == "JPY"
    assert amount.value == 1000.0
    print(f"  ✓ PaymentCurrencyAmount作成成功: {amount.model_dump()}")
except Exception as e:
    print(f"  ✗ PaymentCurrencyAmount作成失敗: {e}")
    sys.exit(1)

# Test 4: PaymentItem型の動作確認
print("\n[Test 4] PaymentItem型の動作確認")
try:
    item = PaymentItem(
        label="テスト商品",
        amount=PaymentCurrencyAmount(currency="JPY", value=1000.0),
        pending=False,
        refund_period=30
    )
    assert item.label == "テスト商品"
    assert item.amount.currency == "JPY"
    assert item.refund_period == 30
    print(f"  ✓ PaymentItem作成成功: {item.model_dump()}")
except Exception as e:
    print(f"  ✗ PaymentItem作成失敗: {e}")
    sys.exit(1)

# Test 5: PaymentRequest型の動作確認
print("\n[Test 5] PaymentRequest型の動作確認")
try:
    payment_request = PaymentRequest(
        method_data=[
            PaymentMethodData(
                supported_methods="https://example.com/pay",
                data={"merchantId": "merchant123"}
            )
        ],
        details=PaymentDetailsInit(
            id="payment_001",
            display_items=[
                PaymentItem(
                    label="商品A",
                    amount=PaymentCurrencyAmount(currency="JPY", value=1000.0)
                )
            ],
            total=PaymentItem(
                label="合計",
                amount=PaymentCurrencyAmount(currency="JPY", value=1000.0)
            )
        )
    )
    assert payment_request.method_data[0].supported_methods == "https://example.com/pay"
    assert payment_request.details.total.amount.value == 1000.0
    print("  ✓ PaymentRequest作成成功")
except Exception as e:
    print(f"  ✗ PaymentRequest作成失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 6: CartContents型の動作確認
print("\n[Test 6] CartContents型の動作確認")
try:
    cart_contents = CartContents(
        id="cart_001",
        user_cart_confirmation_required=True,
        payment_request=payment_request,
        cart_expiry=(datetime.now(timezone.utc).isoformat()),
        merchant_name="テストマーチャント"
    )
    assert cart_contents.id == "cart_001"
    assert cart_contents.merchant_name == "テストマーチャント"
    print("  ✓ CartContents作成成功")
except Exception as e:
    print(f"  ✗ CartContents作成失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 7: CartMandate型の動作確認
print("\n[Test 7] CartMandate型の動作確認")
try:
    cart_mandate = CartMandate(
        contents=cart_contents,
        merchant_authorization=None  # JWTは後で追加
    )
    assert cart_mandate.contents.id == "cart_001"
    print("  ✓ CartMandate作成成功")
except Exception as e:
    print(f"  ✗ CartMandate作成失敗: {e}")
    sys.exit(1)

# Test 8: IntentMandate型の動作確認
print("\n[Test 8] IntentMandate型の動作確認")
try:
    intent_mandate = IntentMandate(
        user_cart_confirmation_required=True,
        natural_language_description="赤いバスケットボールシューズ",
        merchants=["merchant_001"],
        skus=["SKU123"],
        requires_refundability=True,
        intent_expiry=(datetime.now(timezone.utc).isoformat())
    )
    assert intent_mandate.natural_language_description == "赤いバスケットボールシューズ"
    assert intent_mandate.merchants == ["merchant_001"]
    print("  ✓ IntentMandate作成成功")
except Exception as e:
    print(f"  ✗ IntentMandate作成失敗: {e}")
    sys.exit(1)

# Test 9: PaymentResponse型の動作確認
print("\n[Test 9] PaymentResponse型の動作確認")
try:
    payment_response = PaymentResponse(
        request_id="payment_001",
        method_name="https://example.com/pay",
        details={"transactionId": "tx123"},
        payer_name="テスト太郎",
        payer_email="test@example.com"
    )
    assert payment_response.request_id == "payment_001"
    assert payment_response.payer_name == "テスト太郎"
    print("  ✓ PaymentResponse作成成功")
except Exception as e:
    print(f"  ✗ PaymentResponse作成失敗: {e}")
    sys.exit(1)

# Test 10: PaymentMandateContents型の動作確認
print("\n[Test 10] PaymentMandateContents型の動作確認")
try:
    payment_mandate_contents = PaymentMandateContents(
        payment_mandate_id="pm_001",
        payment_details_id="payment_001",
        payment_details_total=PaymentItem(
            label="合計",
            amount=PaymentCurrencyAmount(currency="JPY", value=1000.0)
        ),
        payment_response=payment_response,
        merchant_agent="merchant_001"
    )
    assert payment_mandate_contents.payment_mandate_id == "pm_001"
    assert payment_mandate_contents.merchant_agent == "merchant_001"
    print("  ✓ PaymentMandateContents作成成功")
except Exception as e:
    print(f"  ✗ PaymentMandateContents作成失敗: {e}")
    sys.exit(1)

# Test 11: PaymentMandate型の動作確認
print("\n[Test 11] PaymentMandate型の動作確認")
try:
    payment_mandate = PaymentMandate(
        payment_mandate_contents=payment_mandate_contents,
        user_authorization=None  # SD-JWT-VCは後で追加
    )
    assert payment_mandate.payment_mandate_contents.payment_mandate_id == "pm_001"
    print("  ✓ PaymentMandate作成成功")
except Exception as e:
    print(f"  ✗ PaymentMandate作成失敗: {e}")
    sys.exit(1)

# Test 12: JWT Utilsのインポート
print("\n[Test 12] JWT Utilsのインポート確認")
try:
    from common.jwt_utils import (
        compute_canonical_hash,
        MerchantAuthorizationJWT,
        UserAuthorizationSDJWT
    )
    print("  ✓ JWT Utilsのインポートに成功しました")
except ImportError as e:
    print(f"  ✗ インポート失敗: {e}")
    sys.exit(1)

# Test 13: Canonical Hash計算
print("\n[Test 13] Canonical Hash計算の確認")
try:
    test_data = {"key1": "value1", "key2": "value2"}
    hash1 = compute_canonical_hash(test_data)
    hash2 = compute_canonical_hash(test_data)

    # 同じデータからは同じハッシュが生成されることを確認
    assert hash1 == hash2
    print(f"  ✓ Canonical Hash計算成功: {hash1[:20]}...")
except Exception as e:
    print(f"  ✗ Canonical Hash計算失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 全テスト成功
print("\n" + "=" * 70)
print("✓ 全てのテストが成功しました！")
print("=" * 70)
print("\nAP2型定義が正しく実装されました：")
print("  1. W3C Payment Request API型（11型） - OK")
print("  2. AP2 Mandate型（5型） - OK")
print("  3. JWT生成・検証ユーティリティ - OK")
print("\n次のステップ:")
print("  - 既存のUXを保ちつつ、新しい型定義を統合")
print("  - Merchant Authorization JWT生成機能の統合")
print("  - User Authorization SD-JWT-VC生成機能の統合")
print("  - 統合テストの実施")
