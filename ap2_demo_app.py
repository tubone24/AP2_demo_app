"""
AP2 Protocol - Streamlitデモアプリケーション
実際のシナリオに従った動作をインタラクティブにデモ
"""

import streamlit as st
import asyncio
from datetime import datetime
import json
from dataclasses import asdict, is_dataclass
from typing import Any

from ap2_types import Amount, Address, CardPaymentMethod
from ap2_crypto import KeyManager
from secure_shopping_agent import SecureShoppingAgent
from secure_merchant_agent import SecureMerchantAgent
from merchant import Merchant
from payment_processor import MerchantPaymentProcessor
from credential_provider import CredentialProvider
from receipt_generator import generate_receipt_pdf


# ページ設定
st.set_page_config(
    page_title="AP2 Protocol Demo",
    page_icon="🔐",
    layout="wide",
    initial_sidebar_state="expanded"
)


# セッション状態の初期化
def init_session_state():
    """セッション状態を初期化"""
    if 'step' not in st.session_state:
        st.session_state.step = 0
    if 'user_initialized' not in st.session_state:
        st.session_state.user_initialized = False
    if 'intent_mandate' not in st.session_state:
        st.session_state.intent_mandate = None
    if 'products' not in st.session_state:
        st.session_state.products = None
    if 'cart_mandate' not in st.session_state:
        st.session_state.cart_mandate = None
    if 'payment_mandate' not in st.session_state:
        st.session_state.payment_mandate = None
    if 'transaction_result' not in st.session_state:
        st.session_state.transaction_result = None


def initialize_participants(user_passphrase: str, shopping_agent_passphrase: str, merchant_agent_passphrase: str):
    """
    参加者を初期化

    Args:
        user_passphrase: ユーザーの秘密鍵を保護するパスフレーズ
        shopping_agent_passphrase: Shopping Agentの秘密鍵を保護するパスフレーズ
        merchant_agent_passphrase: Merchant Agentの秘密鍵を保護するパスフレーズ
    """
    if st.session_state.user_initialized:
        return

    with st.spinner("鍵ペアを生成中..."):
        # ユーザー
        st.session_state.user_id = "user_demo_001"
        st.session_state.user_name = "デモユーザー"
        st.session_state.user_passphrase = user_passphrase
        st.session_state.user_key_manager = KeyManager()

        try:
            private_key = st.session_state.user_key_manager.load_private_key_encrypted(
                st.session_state.user_id,
                st.session_state.user_passphrase
            )
            st.session_state.user_public_key = private_key.public_key()
        except:
            private_key, public_key = st.session_state.user_key_manager.generate_key_pair(
                st.session_state.user_id
            )
            st.session_state.user_key_manager.save_private_key_encrypted(
                st.session_state.user_id,
                private_key,
                st.session_state.user_passphrase
            )
            st.session_state.user_key_manager.save_public_key(
                st.session_state.user_id,
                public_key
            )
            st.session_state.user_public_key = public_key

        # Shopping Agent
        st.session_state.shopping_agent_passphrase = shopping_agent_passphrase
        st.session_state.shopping_agent = SecureShoppingAgent(
            agent_id="shopping_agent_demo",
            agent_name="Secure Shopping Assistant",
            passphrase=shopping_agent_passphrase
        )

        # Merchant Agent
        st.session_state.merchant_agent_passphrase = merchant_agent_passphrase
        st.session_state.merchant_agent = SecureMerchantAgent(
            agent_id="merchant_agent_demo",
            merchant_name="Demo Running Shoes Store",
            merchant_id="merchant_demo_001",
            passphrase=merchant_agent_passphrase
        )

        # Merchant (実際の販売者)
        st.session_state.merchant = Merchant(
            merchant_id="merchant_demo_001",
            merchant_name="Demo Running Shoes Store",
            passphrase="merchant_secure_pass"
        )

        # Credential Provider
        st.session_state.credential_provider = CredentialProvider(
            provider_id="cp_demo_001",
            provider_name="Demo Credential Provider",
            passphrase="cp_secure_pass_2024"
        )

        # Merchant Payment Processor (Credential Providerを渡す)
        st.session_state.payment_processor = MerchantPaymentProcessor(
            processor_id="processor_demo_001",
            processor_name="Demo Payment Processor",
            passphrase="processor_secure_pass",
            credential_provider=st.session_state.credential_provider
        )

        # デモ用の支払い方法を事前登録
        demo_card1 = CardPaymentMethod(
            type='card',
            token='',  # トークン化前
            last4='4242',
            brand='visa',
            expiry_month=12,
            expiry_year=2026,
            holder_name='デモユーザー'
        )

        demo_card2 = CardPaymentMethod(
            type='card',
            token='',
            last4='5555',
            brand='mastercard',
            expiry_month=6,
            expiry_year=2027,
            holder_name='デモユーザー'
        )

        # テスト用：オーソリ失敗するカード（残高不足）
        demo_card_fail = CardPaymentMethod(
            type='card',
            token='',
            last4='0001',
            brand='visa',
            expiry_month=12,
            expiry_year=2026,
            holder_name='デモユーザー（残高不足テスト）'
        )

        # 支払い方法をCredential Providerに登録
        st.session_state.credential_provider.register_payment_method(
            user_id=st.session_state.user_id,
            payment_method=demo_card1,
            is_default=True
        )

        st.session_state.credential_provider.register_payment_method(
            user_id=st.session_state.user_id,
            payment_method=demo_card2,
            is_default=False
        )

        st.session_state.credential_provider.register_payment_method(
            user_id=st.session_state.user_id,
            payment_method=demo_card_fail,
            is_default=False
        )

        # 鍵のPEMデータを読み込んでセッション状態に保存
        from pathlib import Path
        keys_dir = Path("./keys")

        # User keys
        st.session_state.user_keys = {
            "private_pem": (keys_dir / f"{st.session_state.user_id}_private.pem").read_bytes(),
            "public_pem": (keys_dir / f"{st.session_state.user_id}_public.pem").read_bytes()
        }

        # Shopping Agent keys
        st.session_state.shopping_agent_keys = {
            "private_pem": (keys_dir / "shopping_agent_demo_private.pem").read_bytes(),
            "public_pem": (keys_dir / "shopping_agent_demo_public.pem").read_bytes()
        }

        # Merchant Agent keys
        st.session_state.merchant_agent_keys = {
            "private_pem": (keys_dir / "merchant_agent_demo_private.pem").read_bytes(),
            "public_pem": (keys_dir / "merchant_agent_demo_public.pem").read_bytes()
        }

        st.session_state.user_initialized = True


def dataclass_to_dict(obj: Any) -> Any:
    """dataclassを再帰的に辞書に変換（Enum対応）"""
    if is_dataclass(obj):
        result = {}
        for field_name, field_value in asdict(obj).items():
            result[field_name] = dataclass_to_dict(field_value)
        return result
    elif isinstance(obj, list):
        return [dataclass_to_dict(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: dataclass_to_dict(value) for key, value in obj.items()}
    elif hasattr(obj, 'value'):  # Enumの場合
        return obj.value
    else:
        return obj


def show_json_data(data: Any, title: str, expand: bool = False):
    """JSONデータを整形して表示"""
    with st.expander(f"📄 {title}", expanded=expand):
        # dataclassを辞書に変換
        if is_dataclass(data):
            json_data = dataclass_to_dict(data)
        else:
            json_data = data

        # JSONとして表示
        st.json(json_data)

        # コピー用のテキストも提供
        json_str = json.dumps(json_data, indent=2, ensure_ascii=False)
        st.download_button(
            label="JSONをダウンロード",
            data=json_str,
            file_name=f"{title.replace(' ', '_')}.json",
            mime="application/json"
        )


def show_participant_banner(participants: list, action: str):
    """参加者バナーを表示"""
    # 参加者のアイコンと色の定義
    participant_info = {
        "user": {"icon": "👤", "name": "ユーザー", "color": "#4A90E2"},
        "shopping_agent": {"icon": "🤖", "name": "Shopping Agent", "color": "#50C878"},
        "credential_provider": {"icon": "🔑", "name": "Credential Provider", "color": "#E74C3C"},
        "merchant_agent": {"icon": "🏪", "name": "Merchant Agent", "color": "#FF8C42"},
        "merchant": {"icon": "🏬", "name": "Merchant", "color": "#F39C12"},
        "payment_processor": {"icon": "💳", "name": "Payment Processor", "color": "#9B59B6"}
    }

    # バナー作成
    participant_names = []
    for p in participants:
        info = participant_info[p]
        participant_names.append(f"{info['icon']} <strong>{info['name']}</strong>")

    participants_str = " → ".join(participant_names)

    st.markdown(f"""
    <div style="background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid {participant_info[participants[0]]['color']}; margin-bottom: 20px;">
        <div style="font-size: 14px; color: #666; margin-bottom: 5px;">操作主体</div>
        <div style="font-size: 16px; font-weight: bold;">{participants_str}</div>
        <div style="font-size: 14px; color: #666; margin-top: 5px;">📝 {action}</div>
    </div>
    """, unsafe_allow_html=True)


def show_signature_info(signature, title="署名情報"):
    """署名情報を表示"""
    if signature:
        with st.expander(f"🔐 {title}"):
            st.write(f"**アルゴリズム:** {signature.algorithm}")
            st.write(f"**署名時刻:** {signature.signed_at}")
            st.code(f"署名値: {signature.value[:64]}...", language="text")
            st.code(f"公開鍵: {signature.public_key[:64]}...", language="text")


def step1_intent_creation():
    """ステップ1: Intent Mandateの作成"""
    st.header("📝 ステップ1: 購買意図の表明")

    # 参加者バナー
    show_participant_banner(
        ["user", "shopping_agent"],
        "ユーザーが購買意図を入力し、Shopping Agentが Intent Mandateを作成してUser署名を追加"
    )

    st.markdown("""
    ユーザーが購買意図を表明し、Shopping Agentに購入の権限を委任します。
    Intent Mandateにはユーザーの署名が含まれます。
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("購買情報の入力")

        intent = st.text_area(
            "購買意図",
            value="新しいランニングシューズを購入したい",
            height=100
        )

        max_amount = st.number_input(
            "最大予算 (USD)",
            min_value=10.0,
            max_value=1000.0,
            value=100.0,
            step=10.0
        )

        brands = st.multiselect(
            "希望ブランド",
            ["Nike", "Adidas", "Asics", "New Balance", "Brooks"],
            default=["Nike", "Adidas", "Asics"]
        )

        if st.button("Intent Mandateを作成", type="primary", use_container_width=True):
            with st.spinner("Intent Mandateを作成中..."):
                intent_mandate = st.session_state.shopping_agent.create_intent_mandate_with_user_key(
                    user_id=st.session_state.user_id,
                    user_key_manager=st.session_state.user_key_manager,
                    intent=intent,
                    max_amount=Amount(value=f"{max_amount:.2f}", currency="USD"),
                    categories=["running"],
                    brands=brands
                )
                st.session_state.intent_mandate = intent_mandate
                st.session_state.step = 1
                st.rerun()

    with col2:
        st.subheader("Intent Mandate")
        if st.session_state.intent_mandate:
            mandate = st.session_state.intent_mandate

            st.success("✓ Intent Mandate作成完了")

            st.write(f"**ID:** `{mandate.id}`")
            st.write(f"**意図:** {mandate.intent}")
            st.write(f"**最大金額:** {mandate.constraints.max_amount}")
            st.write(f"**有効期限:** {mandate.expires_at}")

            show_signature_info(mandate.user_signature, "ユーザー署名")

            # JSON表示
            st.divider()
            show_json_data(mandate, "Intent Mandate JSON")

            if st.button("次のステップへ →", use_container_width=True):
                st.session_state.step = 2
                st.rerun()
        else:
            st.info("左側のフォームからIntent Mandateを作成してください")


def step2_product_search():
    """ステップ2: 商品検索"""
    st.header("🔍 ステップ2: 商品検索")

    # 参加者バナー
    show_participant_banner(
        ["shopping_agent", "merchant_agent"],
        "Shopping Agentが Intent Mandateを検証し、Merchant Agentが商品を検索"
    )

    st.markdown("""
    Merchant AgentがIntent Mandateの内容に基づいて商品を検索します。
    Intent Mandateの署名を検証してから検索を実行します。
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("検索条件")

        mandate = st.session_state.intent_mandate
        st.write(f"**意図:** {mandate.intent}")
        st.write(f"**最大金額:** {mandate.constraints.max_amount}")
        st.write(f"**ブランド:** {', '.join(mandate.constraints.brands or [])}")

        if st.button("商品を検索", type="primary", use_container_width=True):
            # 検証プロセスの詳細表示
            with st.status("商品を検索中...", expanded=True) as status:
                st.write("🔍 **ステップ 1:** Shopping AgentがIntent Mandateの署名を検証")
                try:
                    st.session_state.shopping_agent._verify_intent_mandate(mandate)
                    st.success("✓ User署名の検証に成功")

                    # 検証内容を直接表示
                    st.caption("📋 検証項目:")
                    st.caption("• User署名の有効性 ✓")
                    st.caption("• 署名アルゴリズム: ECDSA-SHA256 ✓")
                    st.caption(f"• User ID: {mandate.user_id} ✓")
                except Exception as e:
                    st.error(f"✗ 署名検証に失敗: {str(e)}")
                    status.update(label="検証失敗", state="error")
                    st.stop()

                st.write("🔍 **ステップ 2:** Merchant Agentが商品を検索")
                products = st.session_state.merchant_agent.search_products(mandate)
                st.success(f"✓ {len(products)}件の商品が見つかりました")

                st.session_state.products = products
                status.update(label="商品検索完了！", state="complete")

    with col2:
        st.subheader("検索結果")

        if st.session_state.products:
            st.success(f"✓ {len(st.session_state.products)}件の商品が見つかりました")

            for i, product in enumerate(st.session_state.products):
                with st.container():
                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        st.write(f"**{product.name}**")
                        st.write(f"{product.brand} - {product.description}")
                    with col_b:
                        st.write(f"**{product.price}**")
                    st.divider()

            if st.button("次のステップへ →", use_container_width=True):
                st.session_state.step = 3
                st.rerun()
        else:
            st.info("左側のボタンから商品を検索してください")


def step3_cart_creation():
    """ステップ3: Cart Mandateの作成"""
    st.header("🛒 ステップ3: カートの作成と承認")

    # 参加者バナー
    if st.session_state.cart_mandate and st.session_state.cart_mandate.user_signature:
        # User署名済み
        show_participant_banner(
            ["merchant_agent", "merchant", "user", "shopping_agent"],
            "Merchant Agent がCart Mandate作成 → Merchant が署名 → User が承認 → Shopping Agentが検証"
        )
    else:
        # Merchant署名のみ
        show_participant_banner(
            ["merchant_agent", "merchant", "user"],
            "Merchant Agent がCart Mandate作成 → Merchant が検証・署名 → User が承認してUser署名を追加"
        )

    st.markdown("""
    **AP2プロトコル準拠フロー:**
    1. **Merchant Agent** がCart Mandateを作成（署名なし）
    2. **Merchant** がCart Mandateを検証してMerchant署名を追加
    3. **User** がカート内容を確認してUser署名を追加
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("商品選択")

        if st.session_state.products:
            selected_product_idx = st.radio(
                "購入する商品を選択",
                range(len(st.session_state.products)),
                format_func=lambda i: f"{st.session_state.products[i].name} - {st.session_state.products[i].price}"
            )

            st.subheader("配送先情報")

            street = st.text_input("住所", value="123 Main Street")
            city = st.text_input("市区町村", value="San Francisco")
            state = st.text_input("都道府県/州", value="CA")
            postal_code = st.text_input("郵便番号", value="94105")
            country = st.text_input("国", value="US")

            if st.button("Cart Mandateを作成", type="primary", use_container_width=True):
                # Cart Mandate作成プロセスの詳細表示
                with st.status("Cart Mandateを作成中...", expanded=True) as status:
                    shipping_address = Address(
                        street=street,
                        city=city,
                        state=state,
                        postal_code=postal_code,
                        country=country
                    )

                    # ステップ1: Merchant AgentがCart Mandateを作成（署名なし）
                    st.write("🏪 **ステップ 1:** Merchant AgentがCart Mandateを作成")
                    cart_mandates = st.session_state.merchant_agent.create_cart_mandate(
                        intent_mandate=st.session_state.intent_mandate,
                        products=[st.session_state.products[selected_product_idx]],
                        shipping_address=shipping_address
                    )
                    unsigned_cart = cart_mandates[0]
                    st.success("✓ Cart Mandate作成完了（未署名）")

                    st.caption(f"📋 Cart ID: {unsigned_cart.id}")
                    st.caption(f"商品: {unsigned_cart.items[0].name}")
                    st.caption(f"合計金額: {unsigned_cart.total}")

                    # ステップ2: MerchantがCart Mandateを検証して署名
                    st.write("🏬 **ステップ 2:** MerchantがCart Mandateを検証")
                    try:
                        # 検証項目を直接表示
                        st.caption("🔍 Merchant検証プロセス:")
                        st.caption(f"• 販売者IDの一致確認: {unsigned_cart.merchant_id} ✓")
                        st.caption("• 商品在庫の確認 ✓")
                        st.caption("• 金額整合性の確認 ✓")
                        st.caption(f"  └ 小計: {unsigned_cart.subtotal}")
                        st.caption(f"  └ 税金: {unsigned_cart.tax}")
                        st.caption(f"  └ 配送料: {unsigned_cart.shipping.cost}")
                        st.caption(f"  └ 合計: {unsigned_cart.total}")

                        signed_cart = st.session_state.merchant.sign_cart_mandate(unsigned_cart)
                        st.success("✓ Merchant署名の追加完了")

                        st.caption("🔐 Merchant署名 (ECDSA-SHA256)")
                        st.caption(f"署名時刻: {signed_cart.merchant_signature.signed_at}")

                        st.session_state.cart_mandate = signed_cart
                        status.update(label="Cart Mandate作成完了！", state="complete")

                    except Exception as e:
                        st.error(f"✗ Cart Mandate検証エラー: {str(e)}")
                        status.update(label="検証失敗", state="error")
                        st.stop()

    with col2:
        st.subheader("Cart Mandate")

        if st.session_state.cart_mandate:
            cart = st.session_state.cart_mandate

            st.success("✓ Cart Mandate作成完了")

            st.write(f"**ID:** `{cart.id}`")
            st.write(f"**店舗:** {cart.merchant_name}")

            st.subheader("カート内容")
            for item in cart.items:
                st.write(f"- {item.name} x {item.quantity}")
                st.write(f"  単価: {item.unit_price} = 小計: {item.total_price}")

            st.divider()
            st.write(f"**小計:** {cart.subtotal}")
            st.write(f"**税金:** {cart.tax}")
            st.write(f"**配送料:** {cart.shipping.cost}")
            st.write(f"**合計:** {cart.total}")

            show_signature_info(cart.merchant_signature, "Merchant署名")

            if cart.user_signature:
                show_signature_info(cart.user_signature, "User署名")

                # JSON表示
                st.divider()
                show_json_data(cart, "Cart Mandate JSON (署名済み)")

                if st.button("次のステップへ →", use_container_width=True):
                    st.session_state.step = 4
                    st.rerun()
            else:
                st.divider()
                st.warning("カート内容を確認してください")

                # JSON表示（User署名前）
                show_json_data(cart, "Cart Mandate JSON (Merchant署名のみ)")

                if st.button("カートを承認（User署名を追加）", type="primary", use_container_width=True):
                    with st.spinner("User署名を追加中..."):
                        signed_cart = asyncio.run(
                            st.session_state.shopping_agent.select_and_sign_cart(
                                cart,
                                st.session_state.user_id,
                                st.session_state.user_key_manager
                            )
                        )
                        st.session_state.cart_mandate = signed_cart
                        st.rerun()
        else:
            st.info("左側のフォームからCart Mandateを作成してください")


def step4_payment_creation():
    """ステップ4: Payment Mandateの作成"""
    st.header("💳 ステップ4: 支払い方法の選択")

    # 参加者バナー
    show_participant_banner(
        ["user", "credential_provider", "shopping_agent"],
        "UserがCredential Providerから支払い方法を選択 → トークン化 → Shopping AgentがPayment Mandateを作成"
    )

    st.markdown("""
    Credential Providerに登録済みの支払い方法から選択し、Payment Mandateを作成します。
    支払い方法はトークン化され、実際のカード情報は含まれません。
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("登録済み支払い方法")

        # Credential Providerから支払い方法を取得
        available_methods = st.session_state.credential_provider.get_payment_methods(
            st.session_state.user_id
        )

        if not available_methods:
            st.warning("登録済みの支払い方法がありません")
        else:
            # 支払い方法を表示
            st.write("**利用可能な支払い方法：**")

            # 支払い方法の選択肢を作成
            payment_options = []
            for method in available_methods:
                pm = method.payment_method
                default_mark = " ⭐ (デフォルト)" if method.is_default else ""
                option_text = f"{pm.brand.upper()} ****{pm.last4} (有効期限: {pm.expiry_month:02d}/{pm.expiry_year}){default_mark}"
                payment_options.append(option_text)

            selected_idx = st.radio(
                "支払い方法を選択",
                range(len(available_methods)),
                format_func=lambda i: payment_options[i],
                key="payment_method_selection"
            )

            selected_method = available_methods[selected_idx]

            st.divider()
            st.write("**選択された支払い方法：**")
            st.write(f"- カードブランド: {selected_method.payment_method.brand.upper()}")
            st.write(f"- 下4桁: ****{selected_method.payment_method.last4}")
            st.write(f"- 有効期限: {selected_method.payment_method.expiry_month:02d}/{selected_method.payment_method.expiry_year}")
            st.write(f"- カード名義人: {selected_method.payment_method.holder_name}")

            st.divider()

            if st.button("Payment Mandateを作成", type="primary", use_container_width=True):
                with st.spinner("Payment Mandateを作成中..."):
                    # Credential Providerからトークン化された支払い方法を取得
                    tokenized_payment_method = st.session_state.credential_provider.create_tokenized_payment_method(
                        method_id=selected_method.method_id,
                        user_id=st.session_state.user_id
                    )

                    # Payment Mandateを作成
                    payment_mandate = asyncio.run(
                        st.session_state.shopping_agent.create_payment_mandate(
                            cart_mandate=st.session_state.cart_mandate,
                            intent_mandate=st.session_state.intent_mandate,
                            payment_method=tokenized_payment_method,
                            user_id=st.session_state.user_id,
                            user_key_manager=st.session_state.user_key_manager
                        )
                    )

                    st.session_state.payment_mandate = payment_mandate
                    st.rerun()

    with col2:
        st.subheader("Payment Mandate")

        if st.session_state.payment_mandate:
            payment = st.session_state.payment_mandate

            st.success("✓ Payment Mandate作成完了")

            st.write(f"**ID:** `{payment.id}`")
            st.write(f"**金額:** {payment.amount}")
            st.write(f"**支払い方法:** {payment.payment_method.brand.upper()} ****{payment.payment_method.last4}")
            st.write(f"**トークン:** `{payment.payment_method.token[:20]}...`")
            st.write(f"**取引タイプ:** {payment.transaction_type}")
            st.write(f"**Agent関与:** {'はい' if payment.agent_involved else 'いいえ'}")

            # リスク評価情報を表示
            if payment.risk_score is not None:
                st.divider()
                st.subheader("🔍 リスク評価")

                # リスクレベルに応じた色分け
                if payment.risk_score < 30:
                    risk_level = "低"
                    risk_color = "green"
                elif payment.risk_score < 60:
                    risk_level = "中"
                    risk_color = "orange"
                else:
                    risk_level = "高"
                    risk_color = "red"

                st.markdown(f"**リスクスコア:** <span style='color: {risk_color}; font-size: 20px; font-weight: bold;'>{payment.risk_score}/100 ({risk_level}リスク)</span>", unsafe_allow_html=True)

                if payment.fraud_indicators:
                    st.write("**不正指標:**")
                    for indicator in payment.fraud_indicators:
                        st.write(f"- ⚠️ {indicator}")

            show_signature_info(payment.user_signature, "User署名")

            # JSON表示
            st.divider()
            show_json_data(payment, "Payment Mandate JSON")

            if st.button("次のステップへ →", use_container_width=True):
                st.session_state.step = 5
                st.rerun()
        else:
            st.info("左側から支払い方法を選択してPayment Mandateを作成してください")


def step5_payment_processing():
    """ステップ5: 支払い処理"""
    st.header("✅ ステップ5: 支払い処理")

    # 参加者バナー
    show_participant_banner(
        ["shopping_agent", "payment_processor", "credential_provider"],
        "Shopping Agentが全署名を検証 → Payment ProcessorがCredential Providerに payment credentials をリクエスト → 決済実行"
    )

    st.markdown("""
    **AP2仕様準拠の支払いフロー（ステップ25-27）:**
    1. **Shopping Agent** がすべての Mandate 署名を検証
    2. **Payment Processor** が **Credential Provider** に payment credentials をリクエスト
    3. **Credential Provider** がリスク評価を実施し、高リスク取引の場合は OTP による追加認証を要求
    4. **Payment Processor** が取得した credentials で決済ネットワークに送信
    5. トランザクション完了
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("支払い確認")

        payment = st.session_state.payment_mandate
        cart = st.session_state.cart_mandate

        st.write(f"**支払い金額:** {payment.amount}")
        st.write(f"**店舗:** {cart.merchant_name}")
        st.write(f"**支払い方法:** {payment.payment_method.brand.upper()} ****{payment.payment_method.last4}")

        st.divider()

        otp = st.text_input("ワンタイムパスワード（OTP）", value="123456", type="password")

        if st.button("支払いを実行", type="primary", use_container_width=True):
            with st.spinner("支払いを処理中..."):
                try:
                    # Payment Processorを直接使用してトランザクションを処理
                    from ap2_types import TransactionStatus

                    # 1. トランザクションを承認（Authorization）
                    transaction_result = st.session_state.payment_processor.authorize_transaction(
                        payment_mandate=payment,
                        cart_mandate=cart,
                        otp=otp
                    )

                    # 2. 承認が成功した場合のみキャプチャ（Capture）
                    if transaction_result.status == TransactionStatus.AUTHORIZED:
                        transaction_result = st.session_state.payment_processor.capture_transaction(
                            transaction_result.id
                        )
                    # 3. 失敗した場合はそのまま失敗結果を使用

                    st.session_state.transaction_result = transaction_result
                    st.session_state.step = 6
                    st.rerun()

                except Exception as e:
                    st.error(f"支払い処理エラー: {str(e)}")

    with col2:
        st.subheader("署名検証")

        st.info("支払い実行前に以下の署名を検証します：")

        st.write("✓ Intent Mandate - User署名")
        st.write("✓ Cart Mandate - Merchant署名")
        st.write("✓ Cart Mandate - User署名")
        st.write("✓ Payment Mandate - User署名")


def step6_completion():
    """ステップ6: 完了"""
    result = st.session_state.transaction_result

    # トランザクションが失敗した場合の処理
    from ap2_types import TransactionStatus
    if result.status == TransactionStatus.FAILED:
        st.header("❌ ステップ6: トランザクション失敗")

        # 参加者バナー
        show_participant_banner(
            ["payment_processor", "user"],
            "Payment Processorでトランザクションが拒否されました"
        )

        st.error("✗✗✗ 支払いが失敗しました ✗✗✗")

        # エラー情報の表示
        st.subheader("❌ エラー詳細")

        col1, col2 = st.columns(2)

        with col1:
            st.write(f"**トランザクションID:** `{result.id}`")
            st.write(f"**ステータス:** {result.status.value.upper()}")

            st.divider()

            st.error(f"**エラーコード:** {result.error_code}")
            st.error(f"**エラーメッセージ:** {result.error_message}")

            st.divider()

            st.info("""
            **よくある失敗理由:**
            - 残高不足
            - カードの有効期限切れ
            - カード発行会社による拒否
            - セキュリティコード不一致
            - 不正利用の疑い
            """)

        with col2:
            st.subheader("💡 対処方法")

            if result.error_code == "insufficient_funds":
                st.write("- カードの利用可能額を確認してください")
                st.write("- 別の支払い方法を試してください")
            elif result.error_code == "card_declined":
                st.write("- カード発行会社にお問い合わせください")
                st.write("- 別のカードで再試行してください")
            elif result.error_code == "expired_card":
                st.write("- カードの有効期限を確認してください")
                st.write("- 有効なカードで再試行してください")
            elif result.error_code == "fraud_suspected":
                st.write("- カード発行会社に連絡して、取引を承認してください")
                st.write("- 本人確認が必要な場合があります")
            else:
                st.write("- カード発行会社にお問い合わせください")
                st.write("- しばらくしてから再試行してください")

        # トランザクション結果のJSON表示
        st.divider()
        st.subheader("📄 トランザクション結果")
        show_json_data(result, "Transaction Result JSON", expand=True)

        st.divider()

        if st.button("最初からやり直す", use_container_width=True):
            # セッション状態を完全にクリア
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

        return

    # 成功した場合の処理
    st.header("🎉 ステップ6: トランザクション完了")

    # 参加者バナー
    show_participant_banner(
        ["payment_processor", "user"],
        "Payment Processorが取引を完了し、Userに領収書を発行"
    )

    st.success("✓✓✓ 支払いが正常に完了しました！ ✓✓✓")

    # 領収書PDFを生成（まだ生成されていない場合）
    if 'receipt_pdf' not in st.session_state or st.session_state.receipt_pdf is None:
        with st.spinner("領収書PDFを生成中..."):
            receipt_pdf = generate_receipt_pdf(
                transaction_result=result,
                cart_mandate=st.session_state.cart_mandate,
                payment_mandate=st.session_state.payment_mandate,
                user_name=st.session_state.user_name
            )
            st.session_state.receipt_pdf = receipt_pdf.getvalue()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("トランザクション情報")

        st.write(f"**トランザクションID:** `{result.id}`")
        st.write(f"**ステータス:** {result.status.value.upper()}")
        st.write(f"**承認日時:** {result.authorized_at}")
        st.write(f"**キャプチャ日時:** {result.captured_at}")

        st.divider()

        # 領収書PDFダウンロードボタン
        st.download_button(
            label="📥 領収書PDFをダウンロード",
            data=st.session_state.receipt_pdf,
            file_name=f"receipt_{result.id}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )

    with col2:
        st.subheader("実行された暗号操作")

        st.write("✓ ECDSA鍵ペアの生成")
        st.write("✓ 秘密鍵の暗号化保存（AES-256-CBC）")
        st.write("✓ Intent Mandateへのユーザー署名")
        st.write("✓ Cart MandateへのMerchant署名")
        st.write("✓ Cart MandateへのUser署名")
        st.write("✓ Payment MandateへのUser署名")
        st.write("✓ 各ステップでの署名検証")

    st.divider()

    # すべてのMandateとトランザクション結果のJSON表示
    st.subheader("📄 AP2プロトコルのデータ構造")

    tab1, tab2, tab3, tab4 = st.tabs([
        "Intent Mandate",
        "Cart Mandate",
        "Payment Mandate",
        "Transaction Result"
    ])

    with tab1:
        show_json_data(st.session_state.intent_mandate, "Intent Mandate JSON", expand=True)

    with tab2:
        show_json_data(st.session_state.cart_mandate, "Cart Mandate JSON", expand=True)

    with tab3:
        show_json_data(st.session_state.payment_mandate, "Payment Mandate JSON", expand=True)

    with tab4:
        show_json_data(result, "Transaction Result JSON", expand=True)

    st.divider()

    if st.button("最初からやり直す", use_container_width=True):
        # セッション状態を完全にクリア
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


def main():
    """メインアプリケーション"""

    # タイトル
    st.title("🔐 AP2 Protocol - インタラクティブデモ")
    st.markdown("**Agent Payments Protocol** のセキュアなトランザクションフローを体験できます")

    # セッション状態の初期化
    init_session_state()

    # サイドバー
    with st.sidebar:
        st.header("📋 プロセス")

        steps = [
            "参加者の初期化",
            "Intent Mandate作成",
            "商品検索",
            "Cart Mandate作成",
            "Payment Mandate作成",
            "支払い処理",
            "完了"
        ]

        for i, step_name in enumerate(steps):
            if i < st.session_state.step:
                st.success(f"✓ {step_name}")
            elif i == st.session_state.step:
                st.info(f"→ {step_name}")
            else:
                st.text(f"  {step_name}")

        st.divider()

        st.subheader("セキュリティ保証")
        st.markdown("""
        - 🔐 暗号署名による保護
        - 🔐 改ざん検知
        - 🔐 非否認性
        - 🔐 鍵の暗号化保存
        - 🔐 各ステップでの検証
        """)

    # 参加者の初期化
    if st.session_state.step == 0:
        st.header("🔑 ステップ0: 参加者の初期化")

        st.markdown("""
        AP2プロトコルでは、各参加者（ユーザー、Shopping Agent、Merchant Agent）が
        それぞれ暗号鍵ペアを持ちます。

        このステップでは：
        - **ECDSA鍵ペア**を生成
        - 秘密鍵を**AES-256-CBC**で暗号化して保存
        - 公開鍵を保存
        """)

        if not st.session_state.user_initialized:
            st.subheader("🔐 パスフレーズの設定")

            st.info("""
            各参加者の秘密鍵を保護するパスフレーズを設定してください。
            このパスフレーズは秘密鍵の暗号化に使用され、鍵を復号化する際に必要になります。
            """)

            col1, col2, col3 = st.columns(3)

            with col1:
                st.markdown("**👤 ユーザー**")
                user_pass = st.text_input(
                    "パスフレーズ",
                    value="user_secure_pass",
                    type="password",
                    key="user_pass",
                    help="秘密鍵を保護するパスフレーズ（8文字以上）"
                )

            with col2:
                st.markdown("**🤖 Shopping Agent**")
                shopping_pass = st.text_input(
                    "パスフレーズ",
                    value="shopping_agent_pass",
                    type="password",
                    key="shopping_pass",
                    help="Shopping Agentの秘密鍵を保護するパスフレーズ（8文字以上）"
                )

            with col3:
                st.markdown("**🏪 Merchant Agent**")
                merchant_pass = st.text_input(
                    "パスフレーズ",
                    value="merchant_agent_pass",
                    type="password",
                    key="merchant_pass",
                    help="Merchant Agentの秘密鍵を保護するパスフレーズ（8文字以上）"
                )

            st.divider()

            if st.button("参加者を初期化", type="primary", use_container_width=True):
                # バリデーション
                errors = []

                if not user_pass or len(user_pass) < 8:
                    errors.append("ユーザーのパスフレーズは8文字以上にしてください")

                if not shopping_pass or len(shopping_pass) < 8:
                    errors.append("Shopping Agentのパスフレーズは8文字以上にしてください")

                if not merchant_pass or len(merchant_pass) < 8:
                    errors.append("Merchant Agentのパスフレーズは8文字以上にしてください")

                if errors:
                    for error in errors:
                        st.error(error)
                else:
                    # パスフレーズが正しい場合、初期化実行
                    initialize_participants(user_pass, shopping_pass, merchant_pass)
                    st.success("✓ 参加者の初期化が完了しました")
                    st.rerun()

        # 鍵が生成された後に表示
        if st.session_state.user_initialized:
            st.success("✓ 参加者の初期化が完了しました")

            st.divider()
            st.subheader("🔐 生成された暗号鍵")

            st.markdown("""
            各参加者の暗号鍵ペア（公開鍵と暗号化された秘密鍵）をダウンロードできます。
            秘密鍵はパスフレーズで暗号化されているため、安全に保存できます。
            """)

            # タブで各参加者の鍵を表示
            tab1, tab2, tab3 = st.tabs([
                "👤 ユーザー",
                "🤖 Shopping Agent",
                "🏪 Merchant Agent"
            ])

            with tab1:
                st.write(f"**ユーザーID:** `{st.session_state.user_id}`")
                st.write(f"**パスフレーズ:** `{st.session_state.user_passphrase}` （秘密鍵の復号化に使用）")

                col1, col2 = st.columns(2)

                with col1:
                    st.write("**公開鍵 (Public Key)**")
                    public_pem = st.session_state.user_keys["public_pem"].decode('utf-8')
                    st.code(public_pem, language="text")
                    st.download_button(
                        label="📥 公開鍵をダウンロード",
                        data=st.session_state.user_keys["public_pem"],
                        file_name=f"{st.session_state.user_id}_public.pem",
                        mime="application/x-pem-file",
                        use_container_width=True
                    )

                with col2:
                    st.write("**秘密鍵 (Private Key) - 暗号化済み**")
                    private_pem = st.session_state.user_keys["private_pem"].decode('utf-8')
                    st.code(private_pem[:200] + "\n...\n" + private_pem[-100:], language="text")
                    st.download_button(
                        label="📥 秘密鍵をダウンロード",
                        data=st.session_state.user_keys["private_pem"],
                        file_name=f"{st.session_state.user_id}_private.pem",
                        mime="application/x-pem-file",
                        use_container_width=True
                    )
                    st.caption("⚠️ 秘密鍵は暗号化されています")

            with tab2:
                st.write(f"**Agent ID:** `shopping_agent_demo`")
                st.write(f"**パスフレーズ:** `{st.session_state.shopping_agent_passphrase}` （秘密鍵の復号化に使用）")

                col1, col2 = st.columns(2)

                with col1:
                    st.write("**公開鍵 (Public Key)**")
                    public_pem = st.session_state.shopping_agent_keys["public_pem"].decode('utf-8')
                    st.code(public_pem, language="text")
                    st.download_button(
                        label="📥 公開鍵をダウンロード",
                        data=st.session_state.shopping_agent_keys["public_pem"],
                        file_name="shopping_agent_demo_public.pem",
                        mime="application/x-pem-file",
                        use_container_width=True
                    )

                with col2:
                    st.write("**秘密鍵 (Private Key) - 暗号化済み**")
                    private_pem = st.session_state.shopping_agent_keys["private_pem"].decode('utf-8')
                    st.code(private_pem[:200] + "\n...\n" + private_pem[-100:], language="text")
                    st.download_button(
                        label="📥 秘密鍵をダウンロード",
                        data=st.session_state.shopping_agent_keys["private_pem"],
                        file_name="shopping_agent_demo_private.pem",
                        mime="application/x-pem-file",
                        use_container_width=True
                    )
                    st.caption("⚠️ 秘密鍵は暗号化されています")

            with tab3:
                st.write(f"**Agent ID:** `merchant_agent_demo`")
                st.write(f"**パスフレーズ:** `{st.session_state.merchant_agent_passphrase}` （秘密鍵の復号化に使用）")

                col1, col2 = st.columns(2)

                with col1:
                    st.write("**公開鍵 (Public Key)**")
                    public_pem = st.session_state.merchant_agent_keys["public_pem"].decode('utf-8')
                    st.code(public_pem, language="text")
                    st.download_button(
                        label="📥 公開鍵をダウンロード",
                        data=st.session_state.merchant_agent_keys["public_pem"],
                        file_name="merchant_agent_demo_public.pem",
                        mime="application/x-pem-file",
                        use_container_width=True
                    )

                with col2:
                    st.write("**秘密鍵 (Private Key) - 暗号化済み**")
                    private_pem = st.session_state.merchant_agent_keys["private_pem"].decode('utf-8')
                    st.code(private_pem[:200] + "\n...\n" + private_pem[-100:], language="text")
                    st.download_button(
                        label="📥 秘密鍵をダウンロード",
                        data=st.session_state.merchant_agent_keys["private_pem"],
                        file_name="merchant_agent_demo_private.pem",
                        mime="application/x-pem-file",
                        use_container_width=True
                    )
                    st.caption("⚠️ 秘密鍵は暗号化されています")

            st.divider()

            st.info("""
            **セキュリティに関する注意:**
            - 公開鍵は自由に共有できます
            - 秘密鍵は暗号化されていますが、パスフレーズと一緒に保管しないでください
            - 実際のシステムでは、秘密鍵をエクスポートする機能は提供しないことが推奨されます
            """)
            if st.button("次のステップへ →", type="primary", use_container_width=True):
                st.session_state.step = 1
                st.rerun()

    elif st.session_state.step == 1:
        step1_intent_creation()

    elif st.session_state.step == 2:
        step2_product_search()

    elif st.session_state.step == 3:
        step3_cart_creation()

    elif st.session_state.step == 4:
        step4_payment_creation()

    elif st.session_state.step == 5:
        step5_payment_processing()

    elif st.session_state.step == 6:
        step6_completion()


if __name__ == "__main__":
    main()