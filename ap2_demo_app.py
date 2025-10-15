"""
AP2 Protocol - Streamlitデモアプリケーション
実際のシナリオに従った動作をインタラクティブにデモ
"""

import streamlit as st
import streamlit.components.v1 as components
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
    if 'selected_payment_method' not in st.session_state:
        st.session_state.selected_payment_method = None
    if 'device_attestation' not in st.session_state:
        st.session_state.device_attestation = None
    if 'payment_mandate' not in st.session_state:
        st.session_state.payment_mandate = None
    if 'transaction_result' not in st.session_state:
        st.session_state.transaction_result = None

    # シーケンス4-7用の新しいstate
    if 'credential_providers' not in st.session_state:
        st.session_state.credential_providers = None  # List[CredentialProvider]
    if 'selected_credential_provider' not in st.session_state:
        st.session_state.selected_credential_provider = None  # 選択されたCP
    if 'shipping_address' not in st.session_state:
        st.session_state.shipping_address = None  # Address
    if 'payment_methods' not in st.session_state:
        st.session_state.payment_methods = None  # List[StoredPaymentMethod]


def get_rp_id():
    """
    環境に応じたRelying Party IDを取得

    Returns:
        str: RP ID (localhost or streamlit.app)
    """
    import os

    # Streamlit Cloudで実行されているかチェック
    # Streamlit Cloudの場合、secrets STREAMLIT_SHARING_MODE が設定されている
    if st.secrets["settings"]["STREAMLIT_SHARING_MODE"] == "true" or os.getenv("STREAMLIT_SHARING_MODE") == "true":
        return "ap2demoapp-heqjwhedjhrrcnagsw2thm.streamlit.app"
    else:
        return "localhost"


def initialize_participants(
    user_passphrase: str,
    shopping_agent_passphrase: str,
    merchant_agent_passphrase: str,
    merchant_passphrase: str,
    credential_provider_passphrase: str,
    payment_processor_passphrase: str
):
    """
    参加者を初期化

    Args:
        user_passphrase: ユーザーの秘密鍵を保護するパスフレーズ
        shopping_agent_passphrase: Shopping Agentの秘密鍵を保護するパスフレーズ
        merchant_agent_passphrase: Merchant Agentの秘密鍵を保護するパスフレーズ
        merchant_passphrase: Merchantの秘密鍵を保護するパスフレーズ
        credential_provider_passphrase: Credential Providerの秘密鍵を保護するパスフレーズ
        payment_processor_passphrase: Payment Processorの秘密鍵を保護するパスフレーズ
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
            merchant_name="むぎぼーグッズショップ",
            merchant_id="merchant_demo_001",
            passphrase=merchant_agent_passphrase
        )

        # Merchant (実際の販売者)
        st.session_state.merchant_passphrase = merchant_passphrase
        st.session_state.merchant = Merchant(
            merchant_id="merchant_demo_001",
            merchant_name="むぎぼーグッズショップ",
            passphrase=merchant_passphrase
        )

        # Credential Providers (複数作成 - シーケンス4対応)
        st.session_state.credential_provider_passphrase = credential_provider_passphrase

        # CP1: PayPal風
        cp1 = CredentialProvider(
            provider_id="cp_paypal_demo",
            provider_name="PayPal Wallet",
            passphrase=credential_provider_passphrase
        )

        # CP2: Apple Pay風
        cp2 = CredentialProvider(
            provider_id="cp_applepay_demo",
            provider_name="Apple Pay",
            passphrase=credential_provider_passphrase
        )

        # CP3: Google Pay風
        cp3 = CredentialProvider(
            provider_id="cp_googlepay_demo",
            provider_name="Google Pay",
            passphrase=credential_provider_passphrase
        )

        # 複数のCredential Providersをリストで管理
        st.session_state.credential_providers = [cp1, cp2, cp3]

        # デフォルトのCredential Provider（後で選択可能）
        st.session_state.credential_provider = cp1
        st.session_state.selected_credential_provider = None  # まだ選択されていない

        # Merchant Payment Processor (デフォルトのCredential Providerを渡す)
        st.session_state.payment_processor_passphrase = payment_processor_passphrase
        st.session_state.payment_processor = MerchantPaymentProcessor(
            processor_id="processor_demo_001",
            processor_name="Demo Payment Processor",
            passphrase=payment_processor_passphrase,
            credential_provider=st.session_state.credential_provider
        )

        # デモ用の支払い方法を各Credential Providerに登録

        # CP1 (PayPal): Visa, Mastercardを登録
        cp1_card1 = CardPaymentMethod(
            type='card',
            token='',
            last4='4242',
            brand='visa',
            expiry_month=12,
            expiry_year=2026,
            holder_name='デモユーザー'
        )

        cp1_card2 = CardPaymentMethod(
            type='card',
            token='',
            last4='5555',
            brand='mastercard',
            expiry_month=6,
            expiry_year=2027,
            holder_name='デモユーザー'
        )

        cp1.register_payment_method(
            user_id=st.session_state.user_id,
            payment_method=cp1_card1,
            is_default=True
        )

        cp1.register_payment_method(
            user_id=st.session_state.user_id,
            payment_method=cp1_card2,
            is_default=False
        )

        # CP2 (Apple Pay): Amex, Visaを登録
        cp2_card1 = CardPaymentMethod(
            type='card',
            token='',
            last4='3782',
            brand='amex',
            expiry_month=3,
            expiry_year=2028,
            holder_name='デモユーザー'
        )

        cp2_card2 = CardPaymentMethod(
            type='card',
            token='',
            last4='4111',
            brand='visa',
            expiry_month=9,
            expiry_year=2027,
            holder_name='デモユーザー'
        )

        cp2.register_payment_method(
            user_id=st.session_state.user_id,
            payment_method=cp2_card1,
            is_default=True
        )

        cp2.register_payment_method(
            user_id=st.session_state.user_id,
            payment_method=cp2_card2,
            is_default=False
        )

        # CP3 (Google Pay): Mastercard, JCBを登録
        cp3_card1 = CardPaymentMethod(
            type='card',
            token='',
            last4='2223',
            brand='mastercard',
            expiry_month=11,
            expiry_year=2026,
            holder_name='デモユーザー'
        )

        cp3_card2 = CardPaymentMethod(
            type='card',
            token='',
            last4='3566',
            brand='jcb',
            expiry_month=8,
            expiry_year=2028,
            holder_name='デモユーザー'
        )

        # テスト用：オーソリ失敗するカード（残高不足）
        cp3_card_fail = CardPaymentMethod(
            type='card',
            token='',
            last4='0001',
            brand='visa',
            expiry_month=12,
            expiry_year=2026,
            holder_name='デモユーザー（残高不足テスト）'
        )

        cp3.register_payment_method(
            user_id=st.session_state.user_id,
            payment_method=cp3_card1,
            is_default=True
        )

        cp3.register_payment_method(
            user_id=st.session_state.user_id,
            payment_method=cp3_card2,
            is_default=False
        )

        cp3.register_payment_method(
            user_id=st.session_state.user_id,
            payment_method=cp3_card_fail,
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


def dataclass_to_dict(obj: Any, exclude_none: bool = True) -> Any:
    """
    dataclassを再帰的に辞書に変換（Enum対応）

    Args:
        obj: 変換するオブジェクト
        exclude_none: Noneフィールドを除外するか（AP2仕様推奨）

    Returns:
        辞書表現
    """
    if is_dataclass(obj):
        result = {}
        for field_name, field_value in asdict(obj).items():
            # Noneフィールドを除外（AP2仕様ではnullより未送信が推奨）
            if exclude_none and field_value is None:
                continue
            result[field_name] = dataclass_to_dict(field_value, exclude_none=exclude_none)
        return result
    elif isinstance(obj, list):
        return [dataclass_to_dict(item, exclude_none=exclude_none) for item in obj]
    elif isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if exclude_none and value is None:
                continue
            result[key] = dataclass_to_dict(value, exclude_none=exclude_none)
        return result
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


def create_a2a_message(
    mandate,
    mandate_type: str,
    sender: str = None,
    recipient: str = None,
    sender_signature_manager = None,
    sender_key_id: str = None
):
    """
    MandateからA2Aメッセージを構築

    Args:
        mandate: Mandateオブジェクト
        mandate_type: "IntentMandate", "CartMandate", "PaymentMandate"
        sender: 送信者名（AgentCard URI形式に自動変換）
        recipient: 受信者名（AgentCard URI形式に自動変換）
        sender_signature_manager: 送信者のSignatureManagerインスタンス（オプション）
        sender_key_id: 送信者の鍵ID（オプション、署名時に必要）

    Returns:
        A2Aメッセージオブジェクト（署名付きまたは署名なし）
    """
    from ap2_types import (
        A2AExtensionHeader,
        A2AIntentMandateMessage,
        A2ACartMandateMessage,
        A2APaymentMandateMessage,
        Signature
    )
    from datetime import datetime
    import uuid

    # デフォルトのsender/recipientを設定（AgentCard URI形式）
    if sender is None:
        user_id = getattr(mandate, 'user_id', 'agent_sender')
        sender = f"did:ap2:agent:{user_id}"
    else:
        # Agent名をURI形式に変換
        sender = f"did:ap2:agent:{sender.lower().replace(' ', '_')}"

    if recipient is None:
        # Mandate typeから適切なrecipientを推測（A2A通信では正確なDIDを指定すべき）
        if mandate_type == "IntentMandate":
            # IntentMandateはMerchant Agentへ送信
            recipient = f"did:ap2:agent:merchant_agent"
        elif mandate_type == "CartMandate":
            # CartMandateはShopping Agentまたはユーザーへ返送
            recipient = f"did:ap2:agent:shopping_agent"
        elif mandate_type == "PaymentMandate":
            # PaymentMandateはPayment Processorへ送信
            payee_id = getattr(mandate, 'payee_id', 'payment_processor')
            recipient = f"did:ap2:agent:{payee_id}"
        else:
            recipient = "did:ap2:agent:unknown"
    else:
        # Agent名をURI形式に変換
        recipient = f"did:ap2:agent:{recipient.lower().replace(' ', '_')}"

    # A2A Extension Headerを作成
    header = A2AExtensionHeader(
        message_id=f"msg_{uuid.uuid4().hex[:16]}",
        schema="",  # メッセージごとに設定
        version="0.1",
        timestamp=datetime.utcnow().isoformat() + 'Z',
        sender=sender,
        recipient=recipient,
        signature=None  # 署名は後で追加
    )

    # Mandate typeに応じてA2Aメッセージを構築
    if mandate_type == "IntentMandate":
        header.schema = "a2a://intentmandate/v0.1"  # 仕様準拠：ハイフンなし
        a2a_message = A2AIntentMandateMessage(
            header=header,
            intent_mandate=mandate,
            risk_data=None  # 冗長性削減：risk_payloadはintent_mandate内にあるためnull
        )
    elif mandate_type == "CartMandate":
        header.schema = "a2a://cartmandate/v0.1"  # 仕様準拠：ハイフンなし
        a2a_message = A2ACartMandateMessage(
            header=header,
            cart_mandate=mandate,
            intent_mandate_reference=getattr(mandate, 'intent_mandate_hash', ''),
            risk_data=None  # 冗長性削減：risk_payloadはcart_mandate内にあるためnull
        )
    elif mandate_type == "PaymentMandate":
        header.schema = "a2a://paymentmandate/v0.1"  # 仕様準拠：ハイフンなし
        a2a_message = A2APaymentMandateMessage(
            header=header,
            payment_mandate=mandate,
            cart_mandate_reference=getattr(mandate, 'cart_mandate_hash', ''),
            intent_mandate_reference=getattr(mandate, 'intent_mandate_hash', '')
        )
    else:
        return None

    # オプション：メッセージレベル署名を追加
    if sender_signature_manager and sender_key_id:
        try:
            # A2Aメッセージを辞書に変換
            a2a_dict = dataclass_to_dict(a2a_message)

            # メッセージ全体に署名
            message_signature = sender_signature_manager.sign_a2a_message(
                a2a_dict,
                sender_key_id
            )

            # headerに署名を追加
            header.signature = message_signature

            # A2Aメッセージを再構築（署名付き）
            if mandate_type == "IntentMandate":
                a2a_message = A2AIntentMandateMessage(
                    header=header,
                    intent_mandate=mandate,
                    risk_data=None
                )
            elif mandate_type == "CartMandate":
                a2a_message = A2ACartMandateMessage(
                    header=header,
                    cart_mandate=mandate,
                    intent_mandate_reference=getattr(mandate, 'intent_mandate_hash', ''),
                    risk_data=None
                )
            elif mandate_type == "PaymentMandate":
                a2a_message = A2APaymentMandateMessage(
                    header=header,
                    payment_mandate=mandate,
                    cart_mandate_reference=getattr(mandate, 'cart_mandate_hash', ''),
                    intent_mandate_reference=getattr(mandate, 'intent_mandate_hash', '')
                )
        except Exception as e:
            print(f"[Warning] A2Aメッセージ署名に失敗: {e}")
            # 署名失敗しても、署名なしのメッセージを返す

    return a2a_message


def create_a2a_message_standard(
    mandate,
    mandate_type: str,
    sender: str = None,
    recipient: str = None,
    sender_signature_manager = None,
    sender_key_id: str = None
):
    """
    DataPart形式のA2Aメッセージを構築（A2A仕様準拠）

    Args:
        mandate: Mandateオブジェクト
        mandate_type: "IntentMandate", "CartMandate", "PaymentMandate"
        sender: 送信者名（AgentCard URI形式に自動変換）
        recipient: 受信者名（AgentCard URI形式に自動変換）
        sender_signature_manager: 送信者のSignatureManagerインスタンス（オプション）
        sender_key_id: 送信者の鍵ID（オプション、署名時に必要）

    Returns:
        A2AMessageStandardオブジェクト（DataPart形式）
    """
    from ap2_types import (
        A2AExtensionHeader,
        A2ADataPart,
        A2AMessageStandard
    )
    from datetime import datetime
    import uuid

    # デフォルトのsender/recipientを設定（AgentCard URI形式）
    if sender is None:
        user_id = getattr(mandate, 'user_id', 'agent_sender')
        sender = f"did:ap2:agent:{user_id}"
    else:
        # Agent名をURI形式に変換
        sender = f"did:ap2:agent:{sender.lower().replace(' ', '_')}"

    if recipient is None:
        # Mandate typeから適切なrecipientを推測（A2A通信では正確なDIDを指定）
        if mandate_type == "IntentMandate":
            # IntentMandateはMerchant Agentへ送信
            recipient = f"did:ap2:agent:merchant_agent"
        elif mandate_type == "CartMandate":
            # CartMandateはShopping Agentまたはユーザーへ返送
            recipient = f"did:ap2:agent:shopping_agent"
        elif mandate_type == "PaymentMandate":
            # PaymentMandateはPayment Processorへ送信
            payee_id = getattr(mandate, 'payee_id', 'payment_processor')
            recipient = f"did:ap2:agent:{payee_id}"
        else:
            recipient = "did:ap2:agent:unknown"
    else:
        # Agent名をURI形式に変換
        recipient = f"did:ap2:agent:{recipient.lower().replace(' ', '_')}"

    # Mandate typeに応じてスキーマURIとDataPartキーを設定
    if mandate_type == "IntentMandate":
        schema = "a2a://intentmandate/v0.1"
        data_key = "ap2.mandates.IntentMandate"
    elif mandate_type == "CartMandate":
        schema = "a2a://cartmandate/v0.1"
        data_key = "ap2.mandates.CartMandate"
    elif mandate_type == "PaymentMandate":
        schema = "a2a://paymentmandate/v0.1"
        data_key = "ap2.mandates.PaymentMandate"
    else:
        return None

    # A2A Extension Headerを作成
    header = A2AExtensionHeader(
        message_id=f"msg_{uuid.uuid4().hex[:16]}",
        schema=schema,
        version="0.1",
        timestamp=datetime.utcnow().isoformat() + 'Z',
        sender=sender,
        recipient=recipient,
        signature=None  # 署名は後で追加
    )

    # DataPartを作成
    dataPart = A2ADataPart(
        kind="data",
        data={
            data_key: mandate,
            "risk_data": None
        }
    )

    # A2AMessageを構築
    a2a_message = A2AMessageStandard(
        header=header,
        dataPart=dataPart
    )

    # オプション：メッセージレベル署名を追加
    if sender_signature_manager and sender_key_id:
        try:
            # A2Aメッセージを辞書に変換
            a2a_dict = dataclass_to_dict(a2a_message)

            # メッセージ全体に署名
            message_signature = sender_signature_manager.sign_a2a_message(
                a2a_dict,
                sender_key_id
            )

            # headerに署名を追加
            header.signature = message_signature

            # A2Aメッセージを再構築（署名付き）
            dataPart = A2ADataPart(
                kind="data",
                data={
                    data_key: mandate,
                    "risk_data": None
                }
            )

            a2a_message = A2AMessageStandard(
                header=header,
                dataPart=dataPart
            )
        except Exception as e:
            print(f"[Warning] A2Aメッセージ署名に失敗: {e}")
            # 署名失敗しても、署名なしのメッセージを返す

    return a2a_message


def show_a2a_message(mandate, mandate_type="Mandate"):
    """
    A2Aメッセージペイロード全体を表示

    Args:
        mandate: Mandateオブジェクト
        mandate_type: "IntentMandate", "CartMandate", "PaymentMandate"
    """
    st.subheader("🌐 A2A Protocol Message")

    a2a_message = create_a2a_message_standard(mandate, mandate_type)
    message_format = "DataPart (A2A Message)"

    if not a2a_message:
        st.error(f"不明なMandate Type: {mandate_type}")
        return

    # A2Aメッセージの概要を表示
    st.info(f"""
    **A2A Protocol Message Structure** ({message_format})

    このMandateは以下のA2Aメッセージ構造で送信されます
    - **Schema**: `{a2a_message.header.schema}`
    - **Message ID**: `{a2a_message.header.message_id}`
    - **Timestamp**: `{a2a_message.header.timestamp}`
    - **Format**: {message_format}
    """)

    # A2Aメッセージ全体をJSON表示
    with st.expander("📦 A2A Message Payload", expanded=True):
        # dataclassを辞書に変換してJSON表示
        a2a_dict = dataclass_to_dict(a2a_message)
        st.json(a2a_dict)

        # ダウンロードボタン
        json_str = json.dumps(a2a_dict, indent=2, ensure_ascii=False)
        st.download_button(
            label="A2A Messageをダウンロード",
            data=json_str,
            file_name=f"a2a_{mandate_type.lower()}_{a2a_message.header.message_id}.json",
            mime="application/json"
        )

    # 重要なフィールドをハイライト
    st.caption("✅ **A2A Extension**")

    col1, col2 = st.columns(2)

    with col1:
        if hasattr(mandate, 'mandate_metadata') and mandate.mandate_metadata:
            st.caption(f"• Mandate Hash: `{mandate.mandate_metadata.mandate_hash[:16]}...`")
            if mandate.mandate_metadata.previous_mandate_hash:
                st.caption(f"• Previous Hash: `{mandate.mandate_metadata.previous_mandate_hash[:16]}...` (連鎖)")

        # agent_signalはv0.2以降mandate_metadata内に配置
        agent_sig = None
        if hasattr(mandate, 'mandate_metadata') and mandate.mandate_metadata and mandate.mandate_metadata.agent_signal:
            agent_sig = mandate.mandate_metadata.agent_signal
        elif hasattr(mandate, 'agent_signal') and mandate.agent_signal:
            agent_sig = mandate.agent_signal

        if agent_sig:
            st.caption(f"• Agent Signal: {agent_sig.agent_name} ({agent_sig.autonomous_level})")

    with col2:
        if hasattr(mandate, 'risk_payload') and mandate.risk_payload:
            st.caption(f"• Risk Payload: Device={mandate.risk_payload.platform or 'N/A'}, Session={mandate.risk_payload.session_id[:16] if mandate.risk_payload.session_id else 'N/A'}...")

        if hasattr(mandate, 'intent_mandate_hash') and mandate.intent_mandate_hash:
            st.caption(f"• Intent Hash Ref: `{mandate.intent_mandate_hash[:16]}...`")

        if hasattr(mandate, 'cart_mandate_hash') and mandate.cart_mandate_hash:
            st.caption(f"• Cart Hash Ref: `{mandate.cart_mandate_hash[:16]}...`")


def show_a2a_communication(
    mandate,
    mandate_type: str,
    direction: str,
    sender: str,
    receiver: str,
    use_datapart_format=True
):
    """
    Agent間通信でのA2Aメッセージを表示（expanderなし）

    Args:
        mandate: Mandateオブジェクト
        mandate_type: "IntentMandate", "CartMandate", "PaymentMandate"
        direction: "request" or "response"
        sender: 送信者名
        receiver: 受信者名
        use_datapart_format: DataPart形式を使用するか（デフォルト: True）
    """
    # 通信方向を表示
    if direction == "request":
        icon = "📤"
        label = "Request"
    else:
        icon = "📥"
        label = "Response"

    st.write(f"**{icon} A2A Communication: {sender} → {receiver}**")

    # A2Aメッセージを構築（DataPart形式 or 旧形式）
    if use_datapart_format:
        a2a_message = create_a2a_message_standard(
            mandate, mandate_type, sender=sender, recipient=receiver
        )
        message_format = "DataPart"
    else:
        a2a_message = create_a2a_message(
            mandate, mandate_type, sender=sender, recipient=receiver
        )
        message_format = "Legacy"

    if not a2a_message:
        st.error(f"不明なMandate Type: {mandate_type}")
        return

    st.caption(f"📦 **Schema:** `{a2a_message.header.schema}`")
    st.caption(f"📨 **Message ID:** `{a2a_message.header.message_id}`")


def step1_intent_creation():
    """ステップ1: Intent Mandateの作成"""
    st.header("📝 ステップ1: 購買意図の表明")
    st.caption("🔄 **AP2シーケンス: ステップ 1-3**")

    # 参加者バナー
    show_participant_banner(
        ["user", "shopping_agent"],
        "ユーザーが購買意図を入力し、Shopping Agentが Intent Mandateを作成してUser署名を追加"
    )

    st.markdown("""
    **AP2プロトコルフロー**
    - **ステップ 1:** User → Shopping Agent: Shopping Prompts（購買意図の入力）
    - **ステップ 2:** Shopping Agent → User: IntentMandate confirmation（確認）
    - **ステップ 3:** User → Shopping Agent: Confirm（承認）

    ユーザーが購買意図を表明し、Shopping Agentに購入の権限を委任します。
    Intent Mandateにはユーザーの署名が含まれます。
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("購買情報の入力")

        intent = st.text_area(
            "購買意図",
            value="むぎぼーグッズを購入したい",
            height=100
        )

        max_amount = st.number_input(
            "最大予算 (USD)",
            min_value=10.0,
            max_value=200.0,
            value=50.0,
            step=10.0
        )

        categories = st.multiselect(
            "希望カテゴリ",
            ["stationery", "tableware", "calendar", "interior", "accessories"],
            default=["stationery", "tableware", "accessories"]
        )

        if st.button("Intent Mandateを作成", type="primary", use_container_width=True):
            with st.spinner("Intent Mandateを作成中..."):
                intent_mandate = st.session_state.shopping_agent.create_intent_mandate_with_user_key(
                    user_id=st.session_state.user_id,
                    user_key_manager=st.session_state.user_key_manager,
                    intent=intent,
                    max_amount=Amount(value=f"{max_amount:.2f}", currency="USD"),
                    categories=categories,
                    brands=["むぎぼーオフィシャル"]
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

            # A2Aメッセージを表示
            st.divider()
            show_a2a_message(mandate, "IntentMandate")

            # JSON表示
            st.divider()
            show_json_data(mandate, "Intent Mandate JSON")

            if st.button("次のステップへ →", use_container_width=True):
                st.session_state.step = 2
                st.rerun()
        else:
            st.info("左側のフォームからIntent Mandateを作成してください")


def step2_credential_provider_selection():
    """ステップ2: Credential Provider選択"""
    st.header("🔑 Credential Provider選択")
    st.caption("🔄 **AP2シーケンス: ステップ 4**")

    # 参加者バナー
    show_participant_banner(
        ["user", "shopping_agent"],
        "ユーザーが使用するCredential Providerを選択"
    )

    st.markdown("""
    **AP2プロトコルフロー**
    - **ステップ 4:** User → Shopping Agent: (optional) Credential Provider選択

    ユーザーが使用するCredential Provider（支払い認証情報プロバイダー）を選択します。
    複数のプロバイダーから選択できます（例: PayPal, Apple Pay, Google Pay）。
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("利用可能なCredential Providers")

        # 利用可能なCredential Providersを表示
        providers = st.session_state.credential_providers

        if not providers:
            st.error("Credential Providerが登録されていません")
            return

        # プロバイダー選択
        st.write("**以下から選択してください：**")

        # プロバイダーごとにカードを表示
        for i, provider in enumerate(providers):
            with st.container():
                col_icon, col_info = st.columns([1, 4])

                with col_icon:
                    # プロバイダーのアイコン
                    if "paypal" in provider.provider_id.lower():
                        st.write("💳")
                    elif "apple" in provider.provider_id.lower():
                        st.write("🍎")
                    elif "google" in provider.provider_id.lower():
                        st.write("🔍")
                    else:
                        st.write("🔑")

                with col_info:
                    st.write(f"**{provider.provider_name}**")
                    st.caption(f"Provider ID: `{provider.provider_id}`")

                    # 登録されている支払い方法の数を表示
                    methods = provider.get_payment_methods(st.session_state.user_id)
                    st.caption(f"登録済み支払い方法: {len(methods)}件")

                    # 選択ボタン
                    if st.button(f"{provider.provider_name}を選択", key=f"select_cp_{i}", use_container_width=True):
                        st.session_state.selected_credential_provider = provider
                        st.session_state.credential_provider = provider  # デフォルトのCPも更新

                        # Payment Processorに選択されたCPを設定
                        st.session_state.payment_processor.credential_provider = provider

                        st.success(f"✓ {provider.provider_name}を選択しました")
                        st.rerun()

                st.divider()

    with col2:
        st.subheader("選択されたCredential Provider")

        if st.session_state.selected_credential_provider:
            provider = st.session_state.selected_credential_provider

            st.success(f"✓ **{provider.provider_name}**を選択済み")

            st.write(f"**Provider ID:** `{provider.provider_id}`")

            # 登録されている支払い方法を表示
            methods = provider.get_payment_methods(st.session_state.user_id)

            st.write(f"**登録済み支払い方法:** {len(methods)}件")

            for method in methods:
                pm = method.payment_method
                default_mark = " ⭐ (デフォルト)" if method.is_default else ""
                st.write(f"- {pm.brand.upper()} ****{pm.last4}{default_mark}")

            st.divider()

            st.info("""
            **次のステップ:**
            Credential Providerを選択したら、配送先住所の入力に進みます。
            """)

            if st.button("次のステップへ →", type="primary", use_container_width=True):
                st.session_state.step = 3
                st.rerun()
        else:
            st.info("左側からCredential Providerを選択してください")


def step3_shipping_address_selection():
    """ステップ3: Shipping Address選択"""
    st.header("📦 ステップ3: 配送先住所の入力")
    st.caption("🔄 **AP2シーケンス: ステップ 5**")

    # 参加者バナー
    show_participant_banner(
        ["user", "shopping_agent"],
        "ユーザーが配送先住所を入力してShopping Agentに通知"
    )

    st.markdown("""
    **AP2プロトコルフロー**
    - **ステップ 5:** User → Shopping Agent: (optional) Shipping Address

    ユーザーが商品の配送先住所を入力します。
    この情報はCart Mandate作成時に使用されます。
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("配送先情報の入力")

        street = st.text_input("住所", value="123 Main Street", key="shipping_street")
        city = st.text_input("市区町村", value="San Francisco", key="shipping_city")
        state = st.text_input("都道府県/州", value="CA", key="shipping_state")
        postal_code = st.text_input("郵便番号", value="94105", key="shipping_postal")
        country = st.text_input("国", value="US", key="shipping_country")

        st.divider()

        if st.button("配送先を確定", type="primary", use_container_width=True):
            # Addressオブジェクトを作成
            from ap2_types import Address

            shipping_address = Address(
                street=street,
                city=city,
                state=state,
                postal_code=postal_code,
                country=country
            )

            # Session stateに保存
            st.session_state.shipping_address = shipping_address
            st.success("✓ 配送先住所を保存しました")
            st.rerun()

    with col2:
        st.subheader("確認された配送先")

        if st.session_state.shipping_address:
            addr = st.session_state.shipping_address

            st.success("✓ 配送先住所が確定しました")

            st.write("**配送先:**")
            st.write(f"- {addr.street}")
            st.write(f"- {addr.city}, {addr.state} {addr.postal_code}")
            st.write(f"- {addr.country}")

            st.divider()

            st.info("""
            **次のステップ:**
            配送先を確定したら、Credential Providerから支払い方法を取得します。
            """)

            if st.button("次のステップへ →", type="primary", use_container_width=True):
                st.session_state.step = 4
                st.rerun()
        else:
            st.info("左側のフォームから配送先住所を入力してください")


def step4_payment_methods_get():
    """ステップ4: Payment Methods取得"""
    st.header("💳 ステップ4: 支払い方法の取得")
    st.caption("🔄 **AP2シーケンス: ステップ 6-7**")

    # 参加者バナー
    show_participant_banner(
        ["shopping_agent", "credential_provider"],
        "Shopping AgentがCredential Providerから利用可能な支払い方法を取得"
    )

    st.markdown("""
    **AP2プロトコルフロー**
    - **ステップ 6:** Shopping Agent → Credential Provider: Get Payment Methods
    - **ステップ 7:** Credential Provider → Shopping Agent: { payment methods }

    Shopping Agentが選択されたCredential Providerから、
    ユーザーの利用可能な支払い方法リストを取得します。
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("支払い方法の取得")

        if not st.session_state.selected_credential_provider:
            st.error("Credential Providerが選択されていません")
            st.stop()

        provider = st.session_state.selected_credential_provider

        st.write(f"**Credential Provider:** {provider.provider_name}")
        st.write(f"**Provider ID:** `{provider.provider_id}`")

        st.divider()

        if st.button("支払い方法を取得", type="primary", use_container_width=True):
            with st.spinner("支払い方法を取得中..."):
                # Credential Providerから支払い方法を取得
                methods = provider.get_payment_methods(st.session_state.user_id)

                st.session_state.payment_methods = methods
                st.success(f"✓ {len(methods)}件の支払い方法を取得しました")
                st.rerun()

    with col2:
        st.subheader("取得された支払い方法")

        if st.session_state.payment_methods:
            methods = st.session_state.payment_methods

            st.success(f"✓ {len(methods)}件の支払い方法")

            st.write("**利用可能な支払い方法:**")

            for method in methods:
                pm = method.payment_method
                default_mark = " ⭐ (デフォルト)" if method.is_default else ""
                st.write(f"- **{pm.brand.upper()}** ****{pm.last4}{default_mark}")
                st.caption(f"  有効期限: {pm.expiry_month:02d}/{pm.expiry_year}")

            st.divider()

            st.info("""
            **次のステップ:**
            支払い方法を取得したら、商品検索に進みます。
            """)

            if st.button("次のステップへ →", type="primary", use_container_width=True):
                st.session_state.step = 5
                st.rerun()
        else:
            st.info("左側のボタンから支払い方法を取得してください")


def step5_product_search():
    """ステップ5: 商品検索"""
    st.header("🔍 ステップ5: 商品検索")
    st.caption("🔄 **AP2シーケンス: ステップ 8**")

    # 参加者バナー
    show_participant_banner(
        ["shopping_agent", "merchant_agent"],
        "Shopping Agentが Intent Mandateを検証し、Merchant Agentが商品を検索"
    )

    st.markdown("""
    **AP2プロトコルフロー**
    - **ステップ 8:** Shopping Agent → Merchant Agent: IntentMandate送信

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

                st.write("🔍 **ステップ 2:** Merchant Agentに商品検索リクエストを送信")

                # A2A通信を可視化
                show_a2a_communication(
                    mandate=mandate,
                    mandate_type="IntentMandate",
                    direction="request",
                    sender="Shopping Agent",
                    receiver="Merchant Agent"
                )

                st.caption("📡 実際のシステムでは、このA2AメッセージがHTTP POSTでMerchant AgentのAPIエンドポイントに送信されます")

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
                    col_img, col_info = st.columns([1, 3])
                    with col_img:
                        # 商品画像を表示
                        try:
                            st.image(product.image_url, use_container_width=True)
                        except:
                            st.write("🖼️")
                    with col_info:
                        st.write(f"**{product.name}**")
                        st.write(f"{product.brand}")
                        st.write(f"{product.description}")
                        st.write(f"**価格:** {product.price}")
                    st.divider()

            if st.button("次のステップへ →", use_container_width=True):
                st.session_state.step = 6
                st.rerun()
        else:
            st.info("左側のボタンから商品を検索してください")


def step6_cart_creation():
    """ステップ6: Cart Mandateの作成"""
    st.header("🛒 ステップ6: カートの作成と承認")
    st.caption("🔄 **AP2シーケンス: ステップ 9-12, 15**")

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
    **AP2プロトコルフロー**
    - **ステップ 9:** Merchant Agent内部: Create CartMandate（カート作成）
    - **ステップ 10-11:** Merchant Agent → Merchant: 署名リクエスト & Merchant → Merchant Agent: 署名済みCartMandate返却
    - **ステップ 12:** Merchant Agent → Shopping Agent: 署名済みCartMandate送信
    - **ステップ 15a-b:** Shopping Agent → User: CartMandate表示 & 支払いオプション提示

    **実装フロー:**
    1. **Merchant Agent** がCart Mandateを作成（署名なし）
    2. **Merchant** がCart Mandateを検証してMerchant署名を追加
    3. **User** がカート内容を確認してUser署名を追加
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("商品選択")

        if st.session_state.products:
            st.write("購入する商品を選択してください（複数選択可）")

            # 各商品の選択状態と数量を管理
            selected_products = []
            quantities = {}

            for i, product in enumerate(st.session_state.products):
                col_check, col_img, col_info, col_qty = st.columns([0.5, 1, 2, 1])

                with col_check:
                    is_selected = st.checkbox(f"商品{i+1}を選択", key=f"product_{i}", label_visibility="collapsed")

                with col_img:
                    try:
                        st.image(product.image_url, use_container_width=True)
                    except:
                        st.write("🖼️")

                with col_info:
                    st.write(f"**{product.name}**")
                    st.write(f"{product.price}")
                    st.caption(product.description)

                with col_qty:
                    if is_selected:
                        qty = st.number_input("個", min_value=1, max_value=999, value=1, step=1, key=f"qty_{i}")
                        selected_products.append(product)
                        quantities[product.id] = qty
                    else:
                        st.write("")  # スペーサー

                st.divider()

            if not selected_products:
                st.warning("商品を1つ以上選択してください")

            # 配送先情報の確認（session_stateから取得）
            st.subheader("配送先情報")

            if st.session_state.shipping_address:
                addr = st.session_state.shipping_address
                st.write(f"**配送先:** {addr.street}, {addr.city}, {addr.state} {addr.postal_code}, {addr.country}")
            else:
                st.error("配送先が設定されていません。ステップ3で配送先を入力してください。")
                return

            if st.button("Cart Mandateを作成", type="primary", use_container_width=True):
                # 商品が選択されているか確認
                if not selected_products:
                    st.error("商品を1つ以上選択してください")
                else:
                    # Cart Mandate作成プロセスの詳細表示
                    with st.status("Cart Mandateを作成中...", expanded=True) as status:
                        # session_stateから配送先を取得
                        shipping_address = st.session_state.shipping_address

                        # ステップ1: Merchant AgentがCart Mandateを作成（署名なし）
                        st.write("🏪 **ステップ 1:** Merchant AgentがCart Mandateを作成")
                        unsigned_cart = st.session_state.merchant_agent.create_cart_mandate(
                            intent_mandate=st.session_state.intent_mandate,
                            products=selected_products,
                            quantities=quantities,
                            shipping_address=shipping_address
                        )
                        st.success("✓ Cart Mandate作成完了（未署名）")

                        st.caption(f"📋 Cart ID: {unsigned_cart.id}")
                        st.caption(f"商品数: {len(unsigned_cart.items)}点")
                        st.caption(f"合計金額: {unsigned_cart.total}")

                    # ステップ2: MerchantがCart Mandateを検証して署名
                        st.write("🏬 **ステップ 2:** MerchantにCart Mandate署名リクエストを送信")

                        # A2A通信を可視化
                        show_a2a_communication(
                            mandate=unsigned_cart,
                            mandate_type="CartMandate",
                            direction="request",
                            sender="Merchant Agent",
                            receiver="Merchant"
                        )

                        st.caption("📡 実際のシステムでは、このA2AメッセージがHTTP POSTでMerchantのAPIエンドポイント（署名サービス）に送信されます")

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

                # A2Aメッセージを表示
                st.divider()
                show_a2a_message(cart, "CartMandate")

                # JSON表示
                st.divider()
                show_json_data(cart, "Cart Mandate JSON (署名済み)")

                if st.button("次のステップへ →", use_container_width=True):
                    st.session_state.step = 7
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


def step7_payment_creation():
    """ステップ7: Payment Mandateの作成（Device Attestation統合版）"""
    st.header("💳 ステップ7: 支払い方法の選択とデバイス確認")
    st.caption("🔄 **AP2シーケンス: ステップ 15b, 16-23**")

    # 参加者バナーは状態に応じて変える
    if not st.session_state.selected_payment_method:
        # 状態7a: 支払い方法選択
        show_participant_banner(
            ["user", "shopping_agent", "credential_provider"],
            "Shopping AgentがUserに支払いオプションを提示し、Userが選択してトークン化"
        )
    elif not st.session_state.device_attestation:
        # 状態7b: デバイス確認
        show_participant_banner(
            ["user"],
            "ユーザーが信頼されたデバイスで取引を承認（AP2ステップ20-22）"
        )
    else:
        # 状態7c: Payment Mandate作成
        show_participant_banner(
            ["shopping_agent"],
            "Shopping AgentがDevice AttestationとともにPayment Mandateを作成（AP2ステップ19, 23）"
        )

    st.markdown("""
    **AP2プロトコルフロー**
    - **ステップ 15b:** Shopping Agent → User: Payment Options Prompt（支払いオプション提示）
    - **ステップ 16:** User → Shopping Agent: payment method selection（支払い方法選択）
    - **ステップ 17-18:** Shopping Agent → Credential Provider: Get payment method token（トークン取得）
    - **ステップ 19:** Shopping Agent内部: Create PaymentMandate（Payment Mandate作成）
    - **ステップ 20:** Shopping Agent → User: Redirect to trusted device surface（信頼されたデバイスへリダイレクト）
    - **ステップ 21:** User内部: User confirms purchase & device creates attestation（デバイス証明生成）
    - **ステップ 22:** User → Shopping Agent: {attestation}（証明を送信）
    - **ステップ 23:** Shopping Agent → Credential Provider: PaymentMandate + attestation
    """)

    # --- 状態7a: 支払い方法の選択 ---
    if not st.session_state.selected_payment_method:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("📋 ステップ7a: 支払い方法の選択")
            st.caption("🔄 **シーケンス 15b, 16-18**")

            # ステップ4で取得済みの支払い方法を使用
            if not st.session_state.payment_methods:
                st.error("支払い方法が取得されていません。ステップ4で支払い方法を取得してください。")
                return

            available_methods = st.session_state.payment_methods

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

                if st.button("支払い方法を確定", type="primary", use_container_width=True):
                    with st.spinner("支払い方法をトークン化中..."):
                        # Credential Providerからトークン化された支払い方法を取得
                        tokenized_payment_method = st.session_state.credential_provider.create_tokenized_payment_method(
                            method_id=selected_method.method_id,
                            user_id=st.session_state.user_id
                        )

                        # Session stateに保存
                        st.session_state.selected_payment_method = tokenized_payment_method
                        st.rerun()

        with col2:
            st.subheader("📌 次のステップ")
            st.info("""
            支払い方法を選択すると、次のステップに進みます：

            **ステップ4b: デバイス確認**
            - 信頼されたデバイス（スマートフォン、セキュリティキーなど）で取引を承認
            - デバイスが暗号学的証明（Device Attestation）を生成
            - これにより、取引がリアルタイムで行われていること、デバイスが改ざんされていないことを保証
            """)

    # --- 状態7b: デバイス確認 ---
    elif not st.session_state.device_attestation:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("📱 ステップ7b: デバイス確認")
            st.caption("🔄 **シーケンス 20-22**")

            st.info("""
            **AP2プロトコル ステップ20-22: Device Attestation**

            このステップでは、信頼されたデバイスで取引を承認します。
            実際のシステムでは：
            - Face ID / Touch ID（生体認証）
            - デバイスバインディング
            - セキュアエンクレーブによる証明
            などが使用されます。
            """)

            st.divider()

            # 取引情報の表示
            st.write("**承認する取引情報:**")
            st.write(f"- **店舗:** {st.session_state.cart_mandate.merchant_name}")
            st.write(f"- **金額:** {st.session_state.cart_mandate.total}")
            st.write(f"- **支払い方法:** {st.session_state.selected_payment_method.brand.upper()} ****{st.session_state.selected_payment_method.last4}")

            st.divider()

            # デバイス確認のシミュレーション
            st.warning("🔐 **デバイス認証が必要です**")

            st.markdown("""
            実際のシステムでは、ここでユーザーのデバイス（スマートフォンやセキュリティキー）に
            承認リクエストが送信されます。
            """)

            st.markdown("---")

            st.info("🔑 **Passkey（WebAuthn）認証を使用します**")

            # Passkey登録状態を管理
            if 'passkey_registered' not in st.session_state:
                st.session_state.passkey_registered = False

            # WebAuthn認証の表示状態を管理
            if 'show_webauthn' not in st.session_state:
                st.session_state.show_webauthn = False

            # --- ステップ1: Passkey登録 ---
            if not st.session_state.passkey_registered:
                st.warning("⚠️ **最初にPasskeyを登録してください**")
                st.markdown("""
                Passkeyを登録することで、このデバイスでの認証が可能になります。
                登録は一度だけ必要です。
                """)

                if st.button("✨ Passkeyを登録", type="primary", use_container_width=True, key="register_passkey"):
                    st.session_state.show_webauthn = True
                    st.session_state.webauthn_mode = 'register'
                    st.rerun()

            # --- ステップ2: Passkey認証 ---
            else:
                st.success("✓ Passkeyが登録されています")

                if not st.session_state.show_webauthn:
                    if st.button("🔐 Passkeyで認証開始", type="primary", use_container_width=True):
                        st.session_state.show_webauthn = True
                        st.session_state.webauthn_mode = 'authenticate'
                        st.rerun()

            # --- WebAuthnコンポーネントの表示 ---
            if st.session_state.show_webauthn:
                import base64
                import secrets
                from webauthn_component import webauthn_register, webauthn_authenticate

                # チャレンジを生成（まだ生成されていない場合のみ）
                if 'webauthn_challenge' not in st.session_state or not st.session_state.webauthn_challenge:
                    challenge = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
                    st.session_state.webauthn_challenge = challenge
                else:
                    # 既存のchallengeを再利用
                    challenge = st.session_state.webauthn_challenge

                mode = st.session_state.get('webauthn_mode', 'register')

                if mode == 'register':
                    # 登録モード
                    st.write("### ✨ Passkey登録中...")
                    st.info("ブラウザのプロンプトが表示されます。デバイスの認証（Face ID、Touch ID、PINなど）を完了してください。")

                    # 環境に応じたRP IDを取得
                    rp_id = get_rp_id()

                    webauthn_register(
                        username=st.session_state.user_name,
                        user_id=st.session_state.user_id,
                        rp_name="AP2 Demo",
                        rp_id=rp_id
                    )

                    st.divider()

                    st.info("""
                    **次のステップ:**
                    1. 上記のPasskey登録プロンプトでデバイス認証を完了してください
                    2. 登録が成功したら、下の「登録完了」ボタンをクリックしてください
                    """)

                    if st.button("✅ 登録完了", type="primary", use_container_width=True, key="register_complete"):
                        st.session_state.passkey_registered = True
                        st.session_state.show_webauthn = False
                        st.success("✓ Passkeyの登録が完了しました！")
                        st.rerun()

                else:
                    # 認証モード
                    st.write("### 🔐 Passkey認証中...")

                    # セキュリティ: 古い認証結果をクリア（リプレイ攻撃対策）
                    from webauthn_component import clear_webauthn_auth_result
                    st.info("🔒 **セキュリティチェック:** 古い認証結果をクリアしています...")
                    clear_webauthn_auth_result()

                    st.info("ブラウザのプロンプトが表示されます。デバイスの認証を完了してください。")

                    # WebAuthn認証コンポーネントを表示
                    from webauthn_component import webauthn_authenticate

                    # 環境に応じたRP IDを取得
                    rp_id = get_rp_id()
                    # WebAuthn検証用にrp_idを保存
                    st.session_state.webauthn_rp_id = rp_id

                    webauthn_authenticate(
                        challenge=challenge,
                        rp_id=rp_id,
                        user_id=st.session_state.user_id
                    )

                    st.divider()

                    # ユーザーが認証結果を入力するフォーム
                    st.write("### 📋 認証結果の取得と送信")
                    st.info("**次のステップ:** 上記のWebAuthn認証ボックスに表示されたJSON（グレーの背景）をコピーして、下のテキストエリアに貼り付けてください。")

                    # 初期値として空の文字列を設定（session_stateから取得可能にする）
                    if 'webauthn_json_input' not in st.session_state:
                        st.session_state.webauthn_json_input = ""

                    webauthn_json = st.text_area(
                        "認証結果JSON（上記のボックスから自動入力されます）",
                        value=st.session_state.webauthn_json_input,
                        height=100,
                        key="webauthn_input",
                        help="上記に表示されたJSONが自動的に入力されます。表示されない場合は、ブラウザのコンソールログからコピーしてください。"
                    )

                    col_btn1, col_btn2 = st.columns(2)

                    with col_btn1:
                        if st.button("✅ 認証結果を送信してDevice Attestation生成", type="primary", use_container_width=True, key="confirm_auth_success"):
                            # 認証結果のJSONをパース
                            if webauthn_json:
                                try:
                                    auth_result = json.loads(webauthn_json)

                                    # WebAuthn署名を検証
                                    from ap2_crypto import DeviceAttestationManager
                                    temp_manager = DeviceAttestationManager(st.session_state.user_key_manager)

                                    st.info("🔍 WebAuthn署名を検証しています...")
                                    webauthn_valid = temp_manager.verify_webauthn_signature_simplified(
                                        webauthn_auth_result=auth_result,
                                        challenge=st.session_state.webauthn_challenge,
                                        rp_id=st.session_state.webauthn_rp_id
                                    )

                                    if not webauthn_valid:
                                        st.error("❌ WebAuthn署名の検証に失敗しました")
                                        st.error("認証データが改ざんされているか、チャレンジが一致しません")
                                        st.stop()

                                    st.success("✓ WebAuthn署名を検証しました")

                                    st.session_state.webauthn_auth_result = auth_result
                                    st.session_state.auth_check_requested = True
                                    st.rerun()
                                except json.JSONDecodeError as e:
                                    st.error(f"❌ JSONのパースに失敗しました: {str(e)}")
                            else:
                                st.error("❌ 認証結果が入力されていません")

                    with col_btn2:
                        if st.button("🔄 認証をやり直す", use_container_width=True, key="retry_auth"):
                            # ローカルストレージをクリアして再試行
                            st.session_state.show_webauthn = False
                            st.session_state.webauthn_json_input = ""
                            # 新しい認証用にchallengeをクリア（再生成させる）
                            if 'webauthn_challenge' in st.session_state:
                                del st.session_state.webauthn_challenge
                            if 'webauthn_auth_result' in st.session_state:
                                del st.session_state.webauthn_auth_result
                            st.rerun()

                # Device Attestationが既に生成されている場合、完了状態を表示
                if st.session_state.device_attestation is not None:
                    # 生成完了の表示を維持
                    with st.status("✅ Device Attestation生成完了！", state="complete", expanded=True):
                        st.write("🔐 **ステップ 1:** デバイスがチャレンジを生成")
                        st.write("🔐 **ステップ 2:** Passkey認証完了")
                        st.write("🔐 **ステップ 3:** デバイスが暗号学的証明を生成")

                        st.success("✓ Device Attestation生成完了")
                        attestation = st.session_state.device_attestation
                        st.caption(f"📋 Device ID: {attestation.device_id}")
                        st.caption(f"📋 Platform: {attestation.platform}")
                        st.caption(f"📋 Attestation Type: {attestation.attestation_type.value}")
                        st.caption(f"📋 Timestamp: {attestation.timestamp}")

                # 認証チェックが要求された場合
                elif st.session_state.get('auth_check_requested', False):
                    st.session_state.auth_check_requested = False

                    # Device Attestation生成処理を実行
                    with st.status("Device Attestationを生成中...", expanded=True) as status:
                        import time
                        from ap2_crypto import DeviceAttestationManager
                        from ap2_types import AttestationType, PaymentMandate

                        st.write("🔐 **ステップ 1:** デバイスがチャレンジを生成")
                        time.sleep(0.5)

                        st.write("🔐 **ステップ 2:** Passkey認証完了")
                        time.sleep(0.5)

                        st.write("🔐 **ステップ 3:** デバイスが暗号学的証明を生成")
                        time.sleep(0.5)

                        # Device Attestation Managerを初期化
                        attestation_manager = DeviceAttestationManager(st.session_state.user_key_manager)

                        # Payment Mandate IDを事前に生成（これによりDevice Attestationとの整合性を保つ）
                        import uuid
                        payment_id = f"payment_{uuid.uuid4().hex}"

                        # Device Attestationを生成
                        from dataclasses import dataclass
                        @dataclass
                        class TempPaymentMandate:
                            id: str

                        temp_mandate = TempPaymentMandate(id=payment_id)

                        # WebAuthn認証結果からタイムスタンプを取得（リプレイ攻撃対策）
                        webauthn_timestamp = None
                        if st.session_state.get('webauthn_auth_result'):
                            # JavaScriptのミリ秒タイムスタンプをISO 8601形式に変換
                            timestamp_ms = st.session_state.webauthn_auth_result.get('timestamp')
                            if timestamp_ms:
                                from datetime import datetime
                                dt = datetime.utcfromtimestamp(timestamp_ms / 1000.0)
                                webauthn_timestamp = dt.isoformat() + 'Z'
                                st.caption(f"🔒 WebAuthn認証タイムスタンプを使用: {webauthn_timestamp}")

                        device_attestation = attestation_manager.create_device_attestation(
                            device_id="device_demo_" + st.session_state.user_id,
                            payment_mandate=temp_mandate,
                            device_key_id=st.session_state.user_id,
                            attestation_type=AttestationType.PASSKEY,
                            platform="Web",
                            os_version=None,
                            app_version="1.0.0",
                            timestamp=webauthn_timestamp  # WebAuthn認証の実際のタイムスタンプを使用
                        )

                        st.success("✓ Device Attestation生成完了")
                        st.caption(f"📋 Device ID: {device_attestation.device_id}")
                        st.caption(f"📋 Platform: {device_attestation.platform}")
                        st.caption(f"📋 Attestation Type: {device_attestation.attestation_type.value}")
                        st.caption(f"📋 Timestamp: {device_attestation.timestamp}")

                        # Session stateに保存（Payment IDも保存）
                        st.session_state.device_attestation = device_attestation
                        st.session_state.payment_mandate_id = payment_id  # Payment IDを保存
                        status.update(label="デバイス認証完了！", state="complete")
                        time.sleep(0.5)
                        st.rerun()

        with col2:
            st.subheader("🔒 Device Attestationとは")

            st.markdown("""
            **Device Attestation**は、AP2プロトコルの重要なセキュリティ機能です。

            **目的:**
            - ユーザーが信頼されたデバイスで取引を承認したことを証明
            - デバイスが改ざんされていないことを保証
            - 取引がリアルタイムで行われていることを保証（リプレイ攻撃対策）

            **技術的な仕組み:**
            1. デバイスがランダムなチャレンジ値を生成
            2. ユーザーが生体認証などで承認
            3. デバイスの秘密鍵で取引情報とチャレンジに署名
            4. 署名、チャレンジ、タイムスタンプを含むAttestationを生成

            **検証:**
            - Credential ProviderがAttestationの署名を検証
            - タイムスタンプの鮮度をチェック（5分以内）
            - デバイスの公開鍵で署名が正しいことを確認
            """)

            st.info("""
            💡 **セキュリティのポイント:**

            Device Attestationにより、以下の攻撃を防ぎます：
            - リプレイ攻撃（古い取引を再送信）
            - マルウェアによるトランザクション改ざん
            - 不正なデバイスからの取引
            """)

    # --- 状態7c: Payment Mandate作成 ---
    else:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("✅ ステップ7c: デバイス確認完了")
            st.caption("🔄 **シーケンス 19, 23**")

            st.success("✓ Device Attestation生成完了")

            # Device Attestation情報を表示
            attestation = st.session_state.device_attestation
            st.write(f"**Device ID:** `{attestation.device_id}`")
            st.write(f"**Platform:** {attestation.platform} {attestation.os_version or ''}")
            st.write(f"**Attestation Type:** {attestation.attestation_type.value}")
            st.write(f"**Timestamp:** {attestation.timestamp}")

            st.divider()

            # Payment Mandate作成ボタン
            if not st.session_state.payment_mandate:
                if st.button("Payment Mandateを作成", type="primary", use_container_width=True):
                    with st.spinner("Payment Mandateを作成中..."):
                        # Payment Mandateを作成（Device Attestation付き）
                        # Session stateに保存したpayment_idを使用（Device Attestationとの整合性を保つ）
                        payment_mandate = asyncio.run(
                            st.session_state.shopping_agent.create_payment_mandate(
                                cart_mandate=st.session_state.cart_mandate,
                                intent_mandate=st.session_state.intent_mandate,
                                payment_method=st.session_state.selected_payment_method,
                                user_id=st.session_state.user_id,
                                user_key_manager=st.session_state.user_key_manager,
                                device_attestation=st.session_state.device_attestation,
                                payment_id=st.session_state.payment_mandate_id  # Device Attestation作成時と同じIDを使用
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

                # Device Attestation情報を表示
                if payment.device_attestation:
                    st.divider()
                    st.subheader("🔐 Device Attestation")
                    st.write(f"**Device ID:** {payment.device_attestation.device_id}")
                    st.write(f"**Platform:** {payment.device_attestation.platform}")
                    st.write(f"**Attestation Type:** {payment.device_attestation.attestation_type.value}")
                    st.write(f"**Timestamp:** {payment.device_attestation.timestamp}")

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

                # A2Aメッセージを表示
                st.divider()
                show_a2a_message(payment, "PaymentMandate")

                # JSON表示
                st.divider()
                show_json_data(payment, "Payment Mandate JSON")

                if st.button("次のステップへ →", use_container_width=True):
                    st.session_state.step = 8
                    st.rerun()
            else:
                st.info("左側のボタンからPayment Mandateを作成してください")


def step8_payment_processing():
    """ステップ8: 支払い処理"""
    st.header("✅ ステップ8: 支払い処理")
    st.caption("🔄 **AP2シーケンス: ステップ 24-31**")

    # 参加者バナー
    show_participant_banner(
        ["shopping_agent", "payment_processor", "credential_provider"],
        "Shopping Agentが全署名を検証 → Payment ProcessorがCredential Providerに payment credentials をリクエスト → 決済実行"
    )

    st.markdown("""
    **AP2プロトコルフロー**
    - **ステップ 24:** Shopping Agent → Merchant Agent: purchase {PaymentMandate + attestation}
    - **ステップ 25:** Merchant Agent → Merchant Payment Processor: initiate payment {PaymentMandate + attestation}
    - **ステップ 26:** Merchant Payment Processor → Credential Provider: request payment credentials {PaymentMandate}
    - **ステップ 27:** Credential Provider → Merchant Payment Processor: {payment credentials}
    - **ステップ 28:** Merchant Payment Processor内部: Process payment（決済処理）
    - **ステップ 29:** Merchant Payment Processor → Credential Provider: Payment receipt
    - **ステップ 30:** Merchant Payment Processor → Merchant Agent: Payment receipt
    - **ステップ 31:** Merchant Agent → Shopping Agent: Payment receipt

    **実装フロー:**
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
            with st.status("支払いを処理中...", expanded=True) as status:
                try:
                    # Payment Processorを直接使用してトランザクションを処理
                    from ap2_types import TransactionStatus

                    st.write("📤 **ステップ 1:** Payment ProcessorにPayment Mandateを送信")

                    # A2A通信を可視化
                    show_a2a_communication(
                        mandate=payment,
                        mandate_type="PaymentMandate",
                        direction="request",
                        sender="Shopping Agent",
                        receiver="Payment Processor"
                    )

                    st.caption("📡 実際のシステムでは、このA2AメッセージがHTTP POSTでPayment ProcessorのAPIエンドポイント（/authorize）に送信されます")

                    st.write("💳 **ステップ 2:** トランザクションを承認（Authorization）")
                    # 1. トランザクションを承認（Authorization）
                    transaction_result = st.session_state.payment_processor.authorize_transaction(
                        payment_mandate=payment,
                        cart_mandate=cart,
                        otp=otp
                    )

                    # 2. 承認が成功した場合のみキャプチャ（Capture）
                    if transaction_result.status == TransactionStatus.AUTHORIZED:
                        st.success("✓ オーソリゼーション成功")
                        st.write("💵 **ステップ 3:** トランザクションをキャプチャ（Capture）")
                        transaction_result = st.session_state.payment_processor.capture_transaction(
                            transaction_result.id
                        )
                        st.success("✓ キャプチャ完了")
                    # 3. 失敗した場合はそのまま失敗結果を使用

                    st.session_state.transaction_result = transaction_result
                    status.update(label="支払い処理完了！", state="complete")
                    st.session_state.step = 9
                    st.rerun()

                except Exception as e:
                    st.error(f"支払い処理エラー: {str(e)}")
                    status.update(label="支払い処理失敗", state="error")

    with col2:
        st.subheader("署名検証")

        st.info("支払い実行前に以下の署名を検証します：")

        st.write("✓ Intent Mandate - User署名")
        st.write("✓ Cart Mandate - Merchant署名")
        st.write("✓ Cart Mandate - User署名")
        st.write("✓ Payment Mandate - User署名")


def step9_completion():
    """ステップ9: 完了"""
    result = st.session_state.transaction_result

    # トランザクションが失敗した場合の処理
    from ap2_types import TransactionStatus
    if result.status == TransactionStatus.FAILED:
        st.header("❌ ステップ9: トランザクション失敗")

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
    st.header("🎉 ステップ9: トランザクション完了")
    st.caption("🔄 **AP2シーケンス: ステップ 32**")

    # 参加者バナー
    show_participant_banner(
        ["payment_processor", "user"],
        "Payment Processorが取引を完了し、Userに領収書を発行"
    )

    st.markdown("""
    **AP2プロトコルフロー**
    - **ステップ 32:** Shopping Agent → User: Purchase completed + receipt（購入完了と領収書）
    """)

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
        show_a2a_message(st.session_state.intent_mandate, "IntentMandate")
        st.divider()
        show_json_data(st.session_state.intent_mandate, "Intent Mandate JSON", expand=True)

    with tab2:
        show_a2a_message(st.session_state.cart_mandate, "CartMandate")
        st.divider()
        show_json_data(st.session_state.cart_mandate, "Cart Mandate JSON", expand=True)

    with tab3:
        show_a2a_message(st.session_state.payment_mandate, "PaymentMandate")
        st.divider()
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
            ("参加者の初期化", "準備"),
            ("Intent Mandate作成", "1-3"),
            ("Credential Provider選択", "4"),
            ("配送先住所入力", "5"),
            ("支払い方法取得", "6-7"),
            ("商品検索", "8"),
            ("Cart Mandate作成", "9-12, 15"),
            ("Payment Mandate作成", "16-23"),
            ("支払い処理", "24-31"),
            ("完了", "32")
        ]

        for i, (step_name, sequence) in enumerate(steps):
            if i < st.session_state.step:
                st.caption(f"シーケンス: {sequence}")
                st.success(f"✓ {step_name}")
            elif i == st.session_state.step:
                st.caption(f"シーケンス: {sequence}")
                st.info(f"→ {step_name}")
            else:
                st.caption(f"シーケンス: {sequence}")
                st.text(f"  {step_name}")

        st.divider()

        st.subheader("References")
        st.markdown("""
        - [AP2 Protocol Specification](https://ap2-protocol.org/specification/)
        - [AP2 GitHub Repository](https://github.com/google-agentic-commerce/AP2)
        """)

    # 参加者の初期化
    if st.session_state.step == 0:
        st.header("🔑 ステップ0: 参加者の初期化")

        st.markdown("""
        AP2プロトコルでは、各参加者（ユーザー、Shopping Agent、Merchant Agent）が
        それぞれ暗号鍵ペアを持ちます。

        このステップでは
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

            st.markdown("**第1グループ: エージェント**")
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
                merchant_agent_pass = st.text_input(
                    "パスフレーズ",
                    value="merchant_agent_pass",
                    type="password",
                    key="merchant_agent_pass",
                    help="Merchant Agentの秘密鍵を保護するパスフレーズ（8文字以上）"
                )

            st.markdown("**第2グループ: インフラストラクチャ**")
            col4, col5, col6 = st.columns(3)

            with col4:
                st.markdown("**🏬 Merchant**")
                merchant_pass = st.text_input(
                    "パスフレーズ",
                    value="merchant_secure_pass",
                    type="password",
                    key="merchant_pass",
                    help="Merchantの秘密鍵を保護するパスフレーズ（8文字以上）"
                )

            with col5:
                st.markdown("**🔑 Credential Provider**")
                cp_pass = st.text_input(
                    "パスフレーズ",
                    value="credential_provider_pass",
                    type="password",
                    key="cp_pass",
                    help="Credential Providerの秘密鍵を保護するパスフレーズ（8文字以上）"
                )

            with col6:
                st.markdown("**💳 Payment Processor**")
                pp_pass = st.text_input(
                    "パスフレーズ",
                    value="payment_processor_pass",
                    type="password",
                    key="pp_pass",
                    help="Payment Processorの秘密鍵を保護するパスフレーズ（8文字以上）"
                )

            st.divider()

            if st.button("参加者を初期化", type="primary", use_container_width=True):
                # バリデーション
                errors = []

                if not user_pass or len(user_pass) < 8:
                    errors.append("ユーザーのパスフレーズは8文字以上にしてください")

                if not shopping_pass or len(shopping_pass) < 8:
                    errors.append("Shopping Agentのパスフレーズは8文字以上にしてください")

                if not merchant_agent_pass or len(merchant_agent_pass) < 8:
                    errors.append("Merchant Agentのパスフレーズは8文字以上にしてください")

                if not merchant_pass or len(merchant_pass) < 8:
                    errors.append("Merchantのパスフレーズは8文字以上にしてください")

                if not cp_pass or len(cp_pass) < 8:
                    errors.append("Credential Providerのパスフレーズは8文字以上にしてください")

                if not pp_pass or len(pp_pass) < 8:
                    errors.append("Payment Processorのパスフレーズは8文字以上にしてください")

                if errors:
                    for error in errors:
                        st.error(error)
                else:
                    # パスフレーズが正しい場合、初期化実行
                    initialize_participants(user_pass, shopping_pass, merchant_agent_pass, merchant_pass, cp_pass, pp_pass)
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
            **セキュリティに関する注意**
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
        step2_credential_provider_selection()

    elif st.session_state.step == 3:
        step3_shipping_address_selection()

    elif st.session_state.step == 4:
        step4_payment_methods_get()

    elif st.session_state.step == 5:
        step5_product_search()

    elif st.session_state.step == 6:
        step6_cart_creation()

    elif st.session_state.step == 7:
        step7_payment_creation()

    elif st.session_state.step == 8:
        step8_payment_processing()

    elif st.session_state.step == 9:
        step9_completion()


if __name__ == "__main__":
    main()