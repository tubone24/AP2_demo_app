#!/usr/bin/env python3
"""
AP2型定義の統合テスト

以下の完全なフローをテスト:
1. CartContents作成 → merchant_authorization JWT生成
2. PaymentMandate作成 → user_authorization SD-JWT-VC生成
3. JWT検証フロー
"""

import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

print("=" * 70)
print("AP2型定義 - 統合テスト")
print("=" * 70)

# 必要なモジュールをインポート
from common.payment_types import (
    PaymentCurrencyAmount,
    PaymentItem,
    PaymentMethodData,
    PaymentDetailsInit,
    PaymentRequest,
    PaymentResponse,
)

from common.mandate_types import (
    CartContents,
    CartMandate,
    PaymentMandateContents,
    PaymentMandate,
)

from common.jwt_utils import (
    compute_canonical_hash,
    MerchantAuthorizationJWT,
    UserAuthorizationSDJWT,
)

from common.crypto import KeyManager, SignatureManager

# Test 1: 一時ディレクトリでKeyManagerをセットアップ
print("\n[Test 1] KeyManagerセットアップ")
try:
    temp_dir = tempfile.mkdtemp()
    key_manager = KeyManager(keys_directory=temp_dir)
    signature_manager = SignatureManager(key_manager)

    # Merchant鍵ペアを生成
    merchant_id = "merchant_test_001"
    merchant_private_key, merchant_public_key = key_manager.generate_key_pair(merchant_id)

    # User鍵ペアを生成
    user_id = "user_test_001"
    user_private_key, user_public_key = key_manager.generate_key_pair(user_id)

    print("  ✓ KeyManagerセットアップ完了")
    print(f"    - Merchant鍵: {merchant_id}")
    print(f"    - User鍵: {user_id}")
except Exception as e:
    print(f"  ✗ KeyManagerセットアップ失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: CartContents作成
print("\n[Test 2] CartContents作成")
try:
    payment_request = PaymentRequest(
        method_data=[
            PaymentMethodData(
                supported_methods="https://example.com/pay",
                data={"merchantId": merchant_id}
            )
        ],
        details=PaymentDetailsInit(
            id="payment_001",
            display_items=[
                PaymentItem(
                    label="テスト商品A",
                    amount=PaymentCurrencyAmount(currency="JPY", value=5000.0)
                ),
                PaymentItem(
                    label="送料",
                    amount=PaymentCurrencyAmount(currency="JPY", value=500.0)
                )
            ],
            total=PaymentItem(
                label="合計",
                amount=PaymentCurrencyAmount(currency="JPY", value=5500.0)
            )
        )
    )

    cart_contents = CartContents(
        id="cart_001",
        user_cart_confirmation_required=True,
        payment_request=payment_request,
        cart_expiry=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        merchant_name="テストマーチャント"
    )

    print("  ✓ CartContents作成成功")
    print(f"    - Cart ID: {cart_contents.id}")
    print(f"    - Total: {cart_contents.payment_request.details.total.amount.value} {cart_contents.payment_request.details.total.amount.currency}")
except Exception as e:
    print(f"  ✗ CartContents作成失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: merchant_authorization JWT生成
print("\n[Test 3] merchant_authorization JWT生成")
try:
    merchant_jwt_helper = MerchantAuthorizationJWT(signature_manager, key_manager)

    merchant_jwt = merchant_jwt_helper.generate(
        merchant_id=merchant_id,
        cart_contents=cart_contents.model_dump(),
        audience="payment_processor",
        expiration_minutes=10,
        algorithm="ECDSA"
    )

    print("  ✓ merchant_authorization JWT生成成功")
    print(f"    - JWT長: {len(merchant_jwt)} 文字")
    print(f"    - JWT先頭: {merchant_jwt[:50]}...")
except Exception as e:
    print(f"  ✗ merchant_authorization JWT生成失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: CartMandate作成（merchant_authorization付き）
print("\n[Test 4] CartMandate作成（merchant_authorization付き）")
try:
    cart_mandate = CartMandate(
        contents=cart_contents,
        merchant_authorization=merchant_jwt
    )

    print("  ✓ CartMandate作成成功")
    print(f"    - merchant_authorization有無: {cart_mandate.merchant_authorization is not None}")
except Exception as e:
    print(f"  ✗ CartMandate作成失敗: {e}")
    sys.exit(1)

# Test 5: merchant_authorization JWT検証
print("\n[Test 5] merchant_authorization JWT検証")
try:
    payload = merchant_jwt_helper.verify(
        jwt=merchant_jwt,
        expected_cart_contents=cart_contents.model_dump()
    )

    print("  ✓ merchant_authorization JWT検証成功")
    print(f"    - Issuer: {payload['iss']}")
    print(f"    - Audience: {payload['aud']}")
    print(f"    - JTI: {payload['jti']}")
    print(f"    - cart_hash: {payload['cart_hash'][:20]}...")
except Exception as e:
    print(f"  ✗ merchant_authorization JWT検証失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 6: PaymentMandateContents作成
print("\n[Test 6] PaymentMandateContents作成")
try:
    payment_response = PaymentResponse(
        request_id="payment_001",
        method_name="https://example.com/pay",
        details={"transactionId": "tx_12345"},
        payer_name="テスト太郎",
        payer_email="test@example.com"
    )

    payment_mandate_contents = PaymentMandateContents(
        payment_mandate_id="pm_001",
        payment_details_id="payment_001",
        payment_details_total=PaymentItem(
            label="合計",
            amount=PaymentCurrencyAmount(currency="JPY", value=5500.0)
        ),
        payment_response=payment_response,
        merchant_agent=merchant_id
    )

    print("  ✓ PaymentMandateContents作成成功")
    print(f"    - Payment Mandate ID: {payment_mandate_contents.payment_mandate_id}")
except Exception as e:
    print(f"  ✗ PaymentMandateContents作成失敗: {e}")
    sys.exit(1)

# Test 7: user_authorization SD-JWT-VC生成
print("\n[Test 7] user_authorization SD-JWT-VC生成")
try:
    user_jwt_helper = UserAuthorizationSDJWT(signature_manager, key_manager)

    nonce = "test_nonce_" + str(datetime.now(timezone.utc).timestamp())

    user_sd_jwt_vc = user_jwt_helper.generate(
        user_id=user_id,
        cart_mandate=cart_mandate.model_dump(),
        payment_mandate_contents=payment_mandate_contents.model_dump(),
        audience="payment_processor",
        nonce=nonce,
        algorithm="ECDSA"
    )

    print("  ✓ user_authorization SD-JWT-VC生成成功")
    print(f"    - SD-JWT-VC長: {len(user_sd_jwt_vc)} 文字")
    print(f"    - 形式確認: ~ 区切り数 = {user_sd_jwt_vc.count('~')}")
except Exception as e:
    print(f"  ✗ user_authorization SD-JWT-VC生成失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 8: PaymentMandate作成（user_authorization付き）
print("\n[Test 8] PaymentMandate作成（user_authorization付き）")
try:
    payment_mandate = PaymentMandate(
        payment_mandate_contents=payment_mandate_contents,
        user_authorization=user_sd_jwt_vc
    )

    print("  ✓ PaymentMandate作成成功")
    print(f"    - user_authorization有無: {payment_mandate.user_authorization is not None}")
except Exception as e:
    print(f"  ✗ PaymentMandate作成失敗: {e}")
    sys.exit(1)

# Test 9: user_authorization SD-JWT-VC検証
print("\n[Test 9] user_authorization SD-JWT-VC検証")
try:
    kb_payload = user_jwt_helper.verify(
        sd_jwt_vc=user_sd_jwt_vc,
        expected_cart_mandate=cart_mandate.model_dump(),
        expected_payment_mandate_contents=payment_mandate_contents.model_dump(),
        expected_nonce=nonce
    )

    print("  ✓ user_authorization SD-JWT-VC検証成功")
    print(f"    - Audience: {kb_payload['aud']}")
    print(f"    - Nonce: {kb_payload['nonce']}")
    print(f"    - transaction_data長: {len(kb_payload['transaction_data'])}")
except Exception as e:
    print(f"  ✗ user_authorization SD-JWT-VC検証失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 10: Canonical Hash一貫性確認
print("\n[Test 10] Canonical Hash一貫性確認")
try:
    # 同じデータから同じハッシュが生成されることを確認
    hash1 = compute_canonical_hash(cart_contents.model_dump())
    hash2 = compute_canonical_hash(cart_contents.model_dump())

    assert hash1 == hash2, "Canonical Hashが一貫していません"

    print("  ✓ Canonical Hash一貫性確認成功")
    print(f"    - Hash: {hash1[:30]}...")
except Exception as e:
    print(f"  ✗ Canonical Hash一貫性確認失敗: {e}")
    sys.exit(1)

# クリーンアップ
print("\n[Cleanup] 一時ディレクトリを削除")
try:
    shutil.rmtree(temp_dir)
    print("  ✓ クリーンアップ完了")
except Exception as e:
    print(f"  ⚠ クリーンアップ警告: {e}")

# 全テスト成功
print("\n" + "=" * 70)
print("✓ 全ての統合テストが成功しました！")
print("=" * 70)
print("\nAP2型定義の統合が完了しました：")
print("  ✓ CartContents + merchant_authorization JWT")
print("  ✓ PaymentMandate + user_authorization SD-JWT-VC")
print("  ✓ JWT生成・検証フロー")
print("  ✓ Canonical Hashの一貫性")
print("\n次のステップ:")
print("  - 実際のサービスに統合（services/merchant, services/shopping_agent）")
print("  - API エンドポイントで新しい型定義を使用")
print("  - E2Eテストの実施")
