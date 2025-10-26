"""
v2/services/shopping_agent/langgraph_shopping_flow.py

LangGraph StateGraphによるショッピングフロー実装

AP2完全準拠：
- IntentMandate → CartMandate → PaymentMandateの署名フロー
- Merchant署名検証
- A2A通信
- WebAuthn/Passkey認証
- LLMによるIntent解析（DMR経由）
- Langfuseトレーシング

設計方針:
- session["step"]に基づいて適切なノードに直接ルーティング
- 各ノードは自分の責務のみを実行
- LLMでIntent解析、金額制約抽出
- 既存のagent.pyのメソッドを最大限活用
"""

import os
import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, TypedDict, Annotated
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

# AP2型定義（完全準拠）
import sys
sys.path.insert(0, '/app')
from ap2_types import Signature

logger = logging.getLogger(__name__)

# Langfuseトレーシング設定
LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
langfuse_handler = None
langfuse_client = None

if LANGFUSE_ENABLED:
    try:
        from langfuse.langchain import CallbackHandler
        from langfuse import Langfuse

        langfuse_client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        )
        langfuse_handler = CallbackHandler()
        logger.info("[Langfuse] Shopping Agent tracing enabled")
    except Exception as e:
        logger.warning(f"[Langfuse] Failed to initialize: {e}")
        LANGFUSE_ENABLED = False


# ============================================================================
# State定義
# ============================================================================

def add_events(existing: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """イベントのreducer（新しいイベントを追加）"""
    return existing + new


class ShoppingFlowState(TypedDict):
    """LangGraph StateGraphの状態"""
    user_input: str
    session_id: str
    session: Dict[str, Any]
    events: Annotated[List[Dict[str, Any]], add_events]
    next_step: Optional[str]
    error: Optional[str]


# ============================================================================
# ルーティング関数（session["step"]ベース）
# ============================================================================

def route_by_step(state: ShoppingFlowState) -> str:
    """
    session["step"]に基づいてノードを選択

    これがLangGraphの正しい使い方：
    - エントリーポイントから、現在の状態に応じて適切なノードに直接ジャンプ
    - 各ノードは自分の責務のみを実行
    """
    session = state["session"]
    current_step = session.get("step", "initial")
    user_input = state["user_input"].lower()

    # リセットキーワード検知
    reset_keywords = ["こんにちは", "hello", "hi", "はじめから", "やり直", "リセット", "reset"]
    should_reset = any(word in user_input for word in reset_keywords)

    if should_reset and current_step in ["error", "completed"]:
        return "greeting"

    # ステップに基づいてルーティング
    if current_step in ["initial", "reset"]:
        return "greeting"
    elif current_step in ["ask_intent", "collecting_intent_info"]:
        return "collect_intent"
    elif current_step in ["intent_complete_ask_shipping", "shipping_address_input"]:
        return "collect_shipping"
    elif current_step == "fetching_carts":
        return "fetch_carts"
    elif current_step in ["cart_selection", "cart_options"]:
        return "select_cart"
    elif current_step == "cart_signature_pending":
        # カート署名待ち（外部API待機）
        return "cart_signature_waiting"
    elif current_step in ["payment_mandate_creation", "select_credential_provider_for_payment", "cp_selection"]:
        # カート署名完了後、Credential Provider選択へ（AP2完全準拠）
        return "select_credential_provider"
    elif current_step in ["payment_method_selection", "payment_method_options"]:
        return "select_payment_method"
    elif current_step == "step_up_requested":
        return "step_up_auth"
    elif current_step in ["webauthn_signature_requested", "webauthn_attestation_requested"]:
        return "webauthn_auth"
    elif current_step == "payment_execution":
        return "execute_payment"
    elif current_step == "completed":
        return "completed"
    elif current_step == "error":
        return "error"
    else:
        logger.warning(f"[route_by_step] Unknown step: {current_step}, routing to error")
        return "error"


# ============================================================================
# ノード実装
# ============================================================================

async def greeting_node(state: ShoppingFlowState) -> ShoppingFlowState:
    """ノード1: 初回挨拶、セッションリセット"""
    session = state["session"]
    user_input_lower = state["user_input"].lower()
    events = []

    # リセットキーワード検知
    reset_keywords = ["こんにちは", "hello", "hi", "はじめから", "やり直", "リセット", "reset"]
    should_reset = any(word in user_input_lower for word in reset_keywords)

    current_step = session.get("step", "initial")

    if should_reset and current_step in ["error", "completed"]:
        # セッションをリセット
        session.clear()
        session["step"] = "initial"
        session["session_id"] = state["session_id"]
        logger.info(f"[greeting_node] Session reset: {state['session_id']}")

    # 初回挨拶
    greeting_msg = "こんにちは！AP2 Shopping Agentです。何をお探しですか？例えば「かわいいグッズがほしい。5000円以内」のように教えてください。"
    for char in greeting_msg:
        events.append({
            "type": "agent_text_chunk",
            "content": char
        })

    events.append({
        "type": "agent_text_complete",
        "content": ""
    })

    session["step"] = "ask_intent"

    return {
        **state,
        "session": session,
        "events": events,
        "next_step": END  # ユーザーの次の入力を待つ
    }


async def collect_intent_node(state: ShoppingFlowState, agent_instance: Any, llm: Optional[ChatOpenAI]) -> ShoppingFlowState:
    """ノード2: Intent収集とIntentMandate作成（LLM統合、Langfuseトレーシング）

    AP2完全準拠：
    - LLMでIntent解析、金額制約抽出
    - IntentMandate作成
    - Langfuseトレーシング
    """
    session = state["session"]
    user_input = state["user_input"]
    events = []
    session_id = state.get("session_id", "unknown")

    # Langfuseスパン開始
    langfuse_span = None
    if LANGFUSE_ENABLED and langfuse_client:
        langfuse_span = langfuse_client.start_span(
            name="collect_intent_node",
            input={"user_input": user_input},
            metadata={"session_id": session_id, "node": "collect_intent"}
        )

    try:
        # ユーザー入力を保存
        session["intent"] = user_input

        # LLMでIntent解析（金額制約抽出含む）
        if llm:
            try:
                system_prompt = """あなたはShopping AgentのIntent分析エキスパートです。
ユーザーの購入要望を解析し、以下の情報を抽出してください:

1. intent: ユーザーの主な要求（そのまま）
2. max_amount: 予算上限（円、数値のみ）
3. keywords: 検索キーワード（日本語、3-5個）

**重要**:
- max_amountは「5000円以内」「1万円まで」等から数値のみ抽出
- keywordsは商品検索に使える日本語キーワード

必ずJSON形式で返答してください。"""

                user_prompt = f"""以下のユーザー要望を分析してください:

{user_input}

JSON形式で返答してください:
{{
  "intent": "...",
  "max_amount": 数値または null,
  "keywords": ["...", "..."]
}}"""

                # LangfuseハンドラーをLLM呼び出しに渡す
                llm_config = {}
                if LANGFUSE_ENABLED and langfuse_handler:
                    llm_config["callbacks"] = [langfuse_handler]

                # LLM呼び出し
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt)
                ]
                response = await llm.ainvoke(messages, config=llm_config)
                response_text = response.content

                # JSON抽出
                # JSONブロックを抽出（```json ... ```で囲まれている場合）
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
                if json_match:
                    json_text = json_match.group(1)
                else:
                    # そのままJSONとしてパース試行
                    json_text = response_text

                intent_data = json.loads(json_text)

                # sessionに保存
                session["intent"] = intent_data.get("intent", user_input)
                if intent_data.get("max_amount"):
                    session["max_amount"] = int(intent_data["max_amount"])

                logger.info(f"[collect_intent_node] LLM result: {intent_data}")

            except Exception as llm_error:
                logger.error(f"[collect_intent_node] LLM error: {llm_error}", exc_info=True)
                # フォールバック: 正規表現
                amount_match = re.search(r'(\d+)\s*円', user_input)
                if amount_match:
                    session["max_amount"] = int(amount_match.group(1))
        else:
            # LLM無効時: 正規表現フォールバック
            amount_match = re.search(r'(\d+)\s*円', user_input)
            if amount_match:
                session["max_amount"] = int(amount_match.group(1))

        # IntentMandate作成（AP2完全準拠）
        intent_mandate = await agent_instance._create_intent_mandate(
            intent=session["intent"],
            session=session
        )

        session["intent_mandate"] = intent_mandate
        session["step"] = "intent_complete_ask_shipping"

        # 確認メッセージ
        confirm_msg = f"承知しました。「{session['intent']}」でお探しします。"
        for char in confirm_msg:
            events.append({
                "type": "agent_text_chunk",
                "content": char
            })

        events.append({
            "type": "agent_text_complete",
            "content": ""
        })

        await asyncio.sleep(0.3)

        # 配送先入力の案内
        shipping_msg = "商品の配送先を入力してください。"
        for char in shipping_msg:
            events.append({
                "type": "agent_text_chunk",
                "content": char
            })

        events.append({
            "type": "agent_text_complete",
            "content": ""
        })

        # 配送先フォーム表示（AP2準拠: ContactAddress形式）
        events.append({
            "type": "shipping_form_request",
            "form_schema": {
                "type": "contact_address",
                "fields": [
                    {"name": "recipient", "label": "受取人名", "type": "text", "required": True},
                    {"name": "postal_code", "label": "郵便番号", "type": "text", "required": True},
                    {"name": "city", "label": "市区町村", "type": "text", "required": True},
                    {"name": "region", "label": "都道府県", "type": "text", "required": True},
                    {"name": "address_line1", "label": "住所1（番地等）", "type": "text", "required": True},
                    {"name": "address_line2", "label": "住所2（建物名等）", "type": "text", "required": False},
                    {"name": "country", "label": "国", "type": "text", "required": True, "default": "JP"},
                    {"name": "phone_number", "label": "電話番号", "type": "text", "required": False},
                ]
            }
        })

        # Langfuseスパン終了
        if langfuse_span:
            langfuse_span.update(
                output={"intent": session["intent"], "max_amount": session.get("max_amount")}
            )
            langfuse_span.end()

        return {
            **state,
            "session": session,
            "events": events,
            "next_step": END  # ユーザーの配送先入力を待つ
        }

    except Exception as err:
        logger.error(f"[collect_intent_node] Error: {err}", exc_info=True)
        session["step"] = "error"
        events.append({
            "type": "agent_text",
            "content": "申し訳ございません。エラーが発生しました。もう一度入力してください。"
        })

        # Langfuseスパン終了（エラー）
        if langfuse_span:
            langfuse_span.update(level="ERROR", output={"error": str(err)})
            langfuse_span.end()

        return {
            **state,
            "session": session,
            "events": events,
            "next_step": END
        }


async def collect_shipping_node(state: ShoppingFlowState, agent_instance: Any) -> ShoppingFlowState:
    """ノード3: 配送先住所入力"""
    session = state["session"]
    user_input = state["user_input"]
    events = []

    try:
        # JSONパース
        shipping_address = json.loads(user_input)

        # AP2準拠のContactAddress形式で保存
        session["shipping_address"] = shipping_address
        session["step"] = "fetching_carts"

        # 確認メッセージ
        recipient = shipping_address.get("recipient", "")
        confirm_msg = f"配送先を設定しました：{recipient} 様"
        for char in confirm_msg:
            events.append({
                "type": "agent_text_chunk",
                "content": char
            })

        events.append({
            "type": "agent_text_complete",
            "content": ""
        })

        await asyncio.sleep(0.3)

        # カート候補取得へ遷移
        return {
            **state,
            "session": session,
            "events": events,
            "next_step": "fetch_carts"  # 次のノードへ直接遷移
        }

    except json.JSONDecodeError:
        logger.error(f"[collect_shipping_node] Invalid JSON: {user_input}")
        events.append({
            "type": "agent_text",
            "content": "配送先の入力形式が不正です。もう一度入力してください。"
        })

        return {
            **state,
            "session": session,
            "events": events,
            "next_step": END
        }


async def fetch_carts_node(state: ShoppingFlowState, agent_instance: Any) -> ShoppingFlowState:
    """ノード4: Merchant Agentからカート候補取得（A2A通信）"""
    session = state["session"]
    events = []

    try:
        # AI分析中メッセージ
        ai_msg = "AI分析でカート候補を作成中..."
        for char in ai_msg:
            events.append({
                "type": "agent_text_chunk",
                "content": char
            })

        events.append({
            "type": "agent_text_complete",
            "content": ""
        })

        # IntentMandateを取得
        intent_mandate = session.get("intent_mandate")
        if not intent_mandate:
            raise ValueError("IntentMandate not found in session")

        # Merchant AgentにA2A通信でカート候補を取得（AP2完全準拠）
        cart_candidates = await agent_instance._search_products_via_merchant_agent(
            intent_mandate=intent_mandate,
            session=session
        )

        if not cart_candidates:
            events.append({
                "type": "agent_text",
                "content": "申し訳ございません。該当する商品が見つかりませんでした。"
            })
            session["step"] = "error"

            return {
                **state,
                "session": session,
                "events": events,
                "next_step": END
            }

        # AP2完全準拠: Artifact構造からフロントエンド用に変換
        frontend_cart_candidates = []
        for i, cart_artifact in enumerate(cart_candidates):
            try:
                # Artifact構造からCartMandateを抽出（AP2/A2A仕様）
                cart_mandate = cart_artifact["parts"][0]["data"]["ap2.mandates.CartMandate"]

                # フロントエンド用のCartCandidate形式に変換
                cart_candidate = {
                    "artifact_id": cart_artifact.get("artifactId", f"artifact_{i}"),
                    "artifact_name": cart_artifact.get("name", f"カート{i+1}"),
                    "cart_mandate": cart_mandate
                }
                frontend_cart_candidates.append(cart_candidate)
            except (KeyError, IndexError) as e:
                logger.error(f"[fetch_carts_node] Failed to extract CartMandate {i}: {e}")

        # セッションに保存
        # - cart_candidates_raw: 元のArtifact構造（A2A準拠、署名検証用）
        # - cart_candidates: フロントエンド用（カート選択処理用）
        session["cart_candidates_raw"] = cart_candidates
        session["cart_candidates"] = frontend_cart_candidates
        session["step"] = "cart_selection"

        # フロントエンドにCartCandidate形式で送信
        events.append({
            "type": "cart_options",
            "items": frontend_cart_candidates
        })

        events.append({
            "type": "agent_text",
            "content": f"{len(cart_candidates)}つのカート候補が見つかりました。お好みのカートを選択してください。"
        })

        return {
            **state,
            "session": session,
            "events": events,
            "next_step": END  # ユーザーのカート選択を待つ
        }

    except Exception as e:
        logger.error(f"[fetch_carts_node] Error: {e}", exc_info=True)
        session["step"] = "error"
        events.append({
            "type": "agent_text",
            "content": f"カート候補の取得中にエラーが発生しました: {str(e)}"
        })

        return {
            **state,
            "session": session,
            "events": events,
            "next_step": END
        }


async def select_cart_node(state: ShoppingFlowState, agent_instance: Any) -> ShoppingFlowState:
    """ノード5: カート選択、Merchant署名検証"""
    session = state["session"]
    user_input = state["user_input"]
    events = []

    try:
        cart_candidates = session.get("cart_candidates", [])

        # カート選択（番号またはID）
        selected_cart_candidate = None
        cart_index = None

        # 番号で選択
        if user_input.isdigit():
            cart_index = int(user_input) - 1
            if 0 <= cart_index < len(cart_candidates):
                selected_cart_candidate = cart_candidates[cart_index]

        # IDで選択（artifact_idまたはcart_mandate.contents.id）
        else:
            for idx, cart in enumerate(cart_candidates):
                cart_mandate = cart.get("cart_mandate", {})
                cart_contents = cart_mandate.get("contents", {})
                if cart.get("artifact_id") == user_input or cart_contents.get("id") == user_input:
                    selected_cart_candidate = cart
                    cart_index = idx
                    break

        if not selected_cart_candidate:
            events.append({
                "type": "agent_text",
                "content": "カートが認識できませんでした。番号（1〜3）またはカートIDを入力してください。"
            })

            return {
                **state,
                "session": session,
                "events": events,
                "next_step": END
            }

        # AP2完全準拠: CartMandateを取得
        cart_mandate = selected_cart_candidate.get("cart_mandate")
        if not cart_mandate:
            raise ValueError("CartMandate not found in selected cart")

        # Merchant署名の暗号学的検証（AP2完全準拠）
        merchant_signature = cart_mandate.get("merchant_signature")
        if not merchant_signature:
            raise ValueError("Merchant signature not found in CartMandate")

        # merchant_signatureをSignatureオブジェクトに変換（AP2完全準拠）
        if isinstance(merchant_signature, dict):
            sig_obj = Signature(**merchant_signature)
        else:
            sig_obj = merchant_signature

        # SignatureManagerでMerchant署名を検証（AP2完全準拠）
        is_valid = agent_instance.signature_manager.verify_mandate_signature(
            cart_mandate,
            sig_obj
        )

        if not is_valid:
            logger.error(f"[select_cart_node] Merchant signature verification FAILED")
            raise ValueError("Merchant署名の検証に失敗しました")

        # CartMandateを保存
        session["cart_mandate"] = cart_mandate
        session["selected_cart_index"] = cart_index
        session["step"] = "cart_signature_pending"

        # WebAuthn署名リクエスト（AP2完全準拠）
        # フロントエンド互換性のため、mandateフィールド名とmandate_type="cart"を使用
        events.append({
            "type": "signature_request",
            "mandate": cart_mandate,
            "mandate_type": "cart"
        })

        return {
            **state,
            "session": session,
            "events": events,
            "next_step": END  # 外部API（POST /cart/submit-signature）を待つ
        }

    except Exception as e:
        logger.error(f"[select_cart_node] Error: {e}", exc_info=True)
        session["step"] = "error"
        events.append({
            "type": "agent_text",
            "content": f"カート選択中にエラーが発生しました: {str(e)}"
        })

        return {
            **state,
            "session": session,
            "events": events,
            "next_step": END
        }


async def cart_signature_waiting_node(state: ShoppingFlowState) -> ShoppingFlowState:
    """カート署名待ち（外部API待機中）（AP2完全準拠）"""
    session = state["session"]
    user_input = state["user_input"]
    events = []

    # `_cart_signature_completed`トークンで署名完了を検知（AP2完全準拠）
    if user_input.startswith("_cart_signature_completed"):
        # 署名完了、次のステップへ
        session["step"] = "payment_mandate_creation"
        events.append({
            "type": "agent_text",
            "content": "✅ CartMandate署名完了しました！"
        })

        return {
            **state,
            "session": session,
            "events": events,
            "next_step": END
        }
    else:
        # 署名待ちメッセージを表示（AP2完全準拠）
        events.append({
            "type": "agent_text",
            "content": "カートの署名を待っています。ブラウザの認証ダイアログで指紋認証・顔認証などを完了してください。"
        })

        return {
            **state,
            "session": session,
            "events": events,
            "next_step": END
        }


async def select_credential_provider_node(state: ShoppingFlowState, agent_instance: Any) -> ShoppingFlowState:
    """ノード6: Credential Provider選択"""
    session = state["session"]
    events = []

    # Credential Provider一覧を取得
    credential_providers = [
        {
            "id": "did:ap2:cp:default",
            "name": "AP2 Credential Provider",
            "url": "http://credential_provider:8003"
        }
    ]

    # デフォルトCPを自動選択
    selected_cp = credential_providers[0]
    session["selected_credential_provider"] = selected_cp
    session["step"] = "payment_method_selection"

    # 支払い方法を取得（AP2完全準拠）
    try:
        payment_methods = await agent_instance._get_payment_methods_from_cp(
            user_id=session.get("user_id", "anonymous"),
            credential_provider_url=selected_cp["url"]
        )

        session["payment_methods"] = payment_methods
        session["available_payment_methods"] = payment_methods  # 既存実装との互換性

        # 支払い方法選択UIを表示（AP2完全準拠）
        events.append({
            "type": "payment_method_selection",
            "payment_methods": payment_methods  # フロントエンド互換性
        })

        return {
            **state,
            "session": session,
            "events": events,
            "next_step": END  # ユーザーの支払い方法選択を待つ
        }

    except Exception as e:
        logger.error(f"[select_credential_provider_node] Error: {e}", exc_info=True)
        session["step"] = "error"
        events.append({
            "type": "agent_text",
            "content": f"支払い方法の取得中にエラーが発生しました: {str(e)}"
        })

        return {
            **state,
            "session": session,
            "events": events,
            "next_step": END
        }


async def select_payment_method_node(state: ShoppingFlowState, agent_instance: Any) -> ShoppingFlowState:
    """ノード7: 支払い方法選択、PaymentMandate作成（AP2完全準拠）"""
    session = state["session"]
    user_input = state["user_input"]
    events = []

    try:
        # 既存実装との互換性のため、available_payment_methodsを優先的に使用
        available_payment_methods = session.get("available_payment_methods", [])
        if not available_payment_methods:
            available_payment_methods = session.get("payment_methods", [])

        if not available_payment_methods:
            events.append({
                "type": "agent_text",
                "content": "申し訳ございません。支払い方法リストが見つかりません。"
            })
            session["step"] = "error"
            return {
                **state,
                "session": session,
                "events": events,
                "next_step": END
            }

        # 支払い方法選択（番号）
        user_input_clean = user_input.strip()
        selected_method = None

        if user_input_clean.isdigit():
            method_index = int(user_input_clean) - 1
            if 0 <= method_index < len(available_payment_methods):
                selected_method = available_payment_methods[method_index]

        if not selected_method:
            events.append({
                "type": "agent_text",
                "content": f"支払い方法が認識できませんでした。番号（1〜{len(available_payment_methods)}）を入力してください。"
            })

            return {
                **state,
                "session": session,
                "events": events,
                "next_step": END
            }

        # 既存実装との互換性: selected_payment_methodをそのまま保存
        session["selected_payment_method"] = selected_method

        # AP2完全準拠: Step-upが必要な支払い方法の場合
        # 既存実装との互換性のため、支払い方法自体のrequires_step_upフィールドをチェック
        if selected_method.get("requires_step_up", False):
            logger.info(
                f"[select_payment_method_node] Payment method requires step-up: "
                f"{selected_method['id']}, brand={selected_method.get('brand', 'unknown')}"
            )
            session["step"] = "step_up_requested"
            return {
                **state,
                "session": session,
                "events": events,
                "next_step": "step_up_auth"
            }

        # トークン化（step-up不要な場合のみ）
        tokenized_method = await agent_instance._tokenize_payment_method(selected_method)
        session["tokenized_payment_method"] = tokenized_method

        # PaymentMandate作成（AP2完全準拠、リスク評価含む）
        cart_mandate = session["cart_mandate"]
        payment_mandate = await agent_instance._create_payment_mandate(
            cart_mandate=cart_mandate,
            payment_method=tokenized_method,
            session=session
        )

        session["payment_mandate"] = payment_mandate

        # PaymentMandateのstep-upチェック（念のため）
        requires_step_up = payment_mandate.get("requires_step_up_authentication", False)

        if requires_step_up:
            session["step"] = "step_up_requested"
            return {
                **state,
                "session": session,
                "events": events,
                "next_step": "step_up_auth"
            }
        else:
            session["step"] = "webauthn_signature_requested"
            return {
                **state,
                "session": session,
                "events": events,
                "next_step": "webauthn_auth"
            }

    except Exception as e:
        logger.error(f"[select_payment_method_node] Error: {e}", exc_info=True)
        session["step"] = "error"
        events.append({
            "type": "agent_text",
            "content": f"支払い方法選択中にエラーが発生しました: {str(e)}"
        })

        return {
            **state,
            "session": session,
            "events": events,
            "next_step": END
        }


async def step_up_auth_node(state: ShoppingFlowState, agent_instance: Any) -> ShoppingFlowState:
    """ノード8: 3D Secure 2.0 Step-up認証"""
    session = state["session"]
    events = []

    # session_idはstateから取得（AP2完全準拠）
    session_id = state.get("session_id", "unknown")

    # 3DS認証URLを表示（AP2完全準拠）
    events.append({
        "type": "stepup_authentication_request",
        "auth_url": "https://example.com/3ds-auth",  # 実際のACS URLを使用
        "challenge": f"3ds_{session_id}"
    })

    session["step"] = "step_up_requested"

    return {
        **state,
        "session": session,
        "events": events,
        "next_step": END  # 外部API（POST /payment/submit-step-up-result）を待つ
    }


async def webauthn_auth_node(state: ShoppingFlowState, agent_instance: Any) -> ShoppingFlowState:
    """ノード9: WebAuthn/Passkey認証"""
    session = state["session"]
    events = []

    payment_mandate = session["payment_mandate"]

    # WebAuthn署名リクエスト（AP2完全準拠）
    # フロントエンド互換性のため、mandateフィールド名とmandate_type="payment"を使用
    events.append({
        "type": "signature_request",
        "mandate": payment_mandate,
        "mandate_type": "payment"
    })

    session["step"] = "webauthn_signature_requested"

    return {
        **state,
        "session": session,
        "events": events,
        "next_step": END  # 外部API（POST /payment/submit-signature）を待つ
    }


async def execute_payment_node(state: ShoppingFlowState, agent_instance: Any) -> ShoppingFlowState:
    """ノード10: 決済実行"""
    session = state["session"]
    events = []

    try:
        payment_mandate = session["payment_mandate"]
        cart_mandate = session["cart_mandate"]

        # Merchant Agentに決済実行（A2A通信、AP2完全準拠）
        result = await agent_instance._process_payment_via_merchant_agent(
            payment_mandate=payment_mandate,
            cart_mandate=cart_mandate,
            session=session
        )

        if result.get("status") == "success":
            session["step"] = "completed"
            session["transaction_result"] = result

            return {
                **state,
                "session": session,
                "events": events,
                "next_step": "completed"
            }
        else:
            raise ValueError(f"Payment failed: {result.get('error')}")

    except Exception as e:
        logger.error(f"[execute_payment_node] Error: {e}", exc_info=True)
        session["step"] = "error"
        events.append({
            "type": "agent_text",
            "content": f"決済実行中にエラーが発生しました: {str(e)}"
        })

        return {
            **state,
            "session": session,
            "events": events,
            "next_step": END
        }


async def completed_node(state: ShoppingFlowState) -> ShoppingFlowState:
    """ノード11: 完了"""
    session = state["session"]
    events = []

    result = session.get("transaction_result", {})

    # 決済完了メッセージと領収書情報（AP2完全準拠）
    receipt_text = f"""✅ 決済が完了しました！

【取引情報】
取引ID: {result.get("transaction_id", "N/A")}
金額: ¥{result.get("amount", {}).get("value", 0):,}
加盟店: {result.get("merchant", "N/A")}

取引は正常に処理されました。"""

    events.append({
        "type": "agent_text",
        "content": receipt_text
    })

    session["step"] = "completed"

    return {
        **state,
        "session": session,
        "events": events,
        "next_step": END
    }


async def error_node(state: ShoppingFlowState) -> ShoppingFlowState:
    """ノード12: エラー"""
    session = state["session"]
    events = []

    error_msg = state.get("error") or "予期しないエラーが発生しました。"

    events.append({
        "type": "agent_text",
        "content": f"❌ {error_msg}\n\n最初からやり直すには「こんにちは」と入力してください。"
    })

    session["step"] = "error"

    return {
        **state,
        "session": session,
        "events": events,
        "next_step": END
    }


# ============================================================================
# グラフ構築
# ============================================================================

def create_shopping_flow_graph(agent_instance: Any):
    """
    ショッピングフローのStateGraphを作成

    設計方針:
    - エントリーポイントからsession["step"]に基づいて適切なノードに直接ルーティング
    - 各ノードは自分の責務のみを実行
    - 無駄なノード遷移を排除

    Args:
        agent_instance: ShoppingAgent インスタンス

    Returns:
        コンパイル済みのStateGraph
    """
    # LLM初期化（DMR: Docker Model Runner）
    dmr_api_url = os.getenv("DMR_API_URL")
    dmr_model = os.getenv("DMR_MODEL", "ai/qwen3")
    dmr_api_key = os.getenv("DMR_API_KEY", "none")

    llm = None
    if dmr_api_url:
        try:
            llm = ChatOpenAI(
                model=dmr_model,
                temperature=0.7,
                openai_api_key=dmr_api_key,
                base_url=dmr_api_url
            )
            logger.info(f"[LangGraph Shopping Flow] LLM initialized: {dmr_model} at {dmr_api_url}")
        except Exception as e:
            logger.warning(f"[LangGraph Shopping Flow] LLM initialization failed: {e}")
            llm = None
    else:
        logger.warning("[LangGraph Shopping Flow] DMR_API_URL not set, LLM disabled")

    # ノード関数にagent_instanceとllmをバインド
    async def greeting_node_bound(state: ShoppingFlowState) -> ShoppingFlowState:
        return await greeting_node(state)

    async def collect_intent_node_bound(state: ShoppingFlowState) -> ShoppingFlowState:
        return await collect_intent_node(state, agent_instance, llm)

    async def collect_shipping_node_bound(state: ShoppingFlowState) -> ShoppingFlowState:
        return await collect_shipping_node(state, agent_instance)

    async def fetch_carts_node_bound(state: ShoppingFlowState) -> ShoppingFlowState:
        return await fetch_carts_node(state, agent_instance)

    async def select_cart_node_bound(state: ShoppingFlowState) -> ShoppingFlowState:
        return await select_cart_node(state, agent_instance)

    async def cart_signature_waiting_node_bound(state: ShoppingFlowState) -> ShoppingFlowState:
        return await cart_signature_waiting_node(state)

    async def select_credential_provider_node_bound(state: ShoppingFlowState) -> ShoppingFlowState:
        return await select_credential_provider_node(state, agent_instance)

    async def select_payment_method_node_bound(state: ShoppingFlowState) -> ShoppingFlowState:
        return await select_payment_method_node(state, agent_instance)

    async def step_up_auth_node_bound(state: ShoppingFlowState) -> ShoppingFlowState:
        return await step_up_auth_node(state, agent_instance)

    async def webauthn_auth_node_bound(state: ShoppingFlowState) -> ShoppingFlowState:
        return await webauthn_auth_node(state, agent_instance)

    async def execute_payment_node_bound(state: ShoppingFlowState) -> ShoppingFlowState:
        return await execute_payment_node(state, agent_instance)

    async def completed_node_bound(state: ShoppingFlowState) -> ShoppingFlowState:
        return await completed_node(state)

    async def error_node_bound(state: ShoppingFlowState) -> ShoppingFlowState:
        return await error_node(state)

    # StateGraphを構築
    workflow = StateGraph(ShoppingFlowState)

    # ノード追加（13ノード）
    workflow.add_node("greeting", greeting_node_bound)
    workflow.add_node("collect_intent", collect_intent_node_bound)
    workflow.add_node("collect_shipping", collect_shipping_node_bound)
    workflow.add_node("fetch_carts", fetch_carts_node_bound)
    workflow.add_node("select_cart", select_cart_node_bound)
    workflow.add_node("cart_signature_waiting", cart_signature_waiting_node_bound)
    workflow.add_node("select_credential_provider", select_credential_provider_node_bound)
    workflow.add_node("select_payment_method", select_payment_method_node_bound)
    workflow.add_node("step_up_auth", step_up_auth_node_bound)
    workflow.add_node("webauthn_auth", webauthn_auth_node_bound)
    workflow.add_node("execute_payment", execute_payment_node_bound)
    workflow.add_node("completed", completed_node_bound)
    workflow.add_node("error", error_node_bound)

    # エントリーポイント: ルーティング関数でstepに基づいて適切なノードに分岐
    workflow.set_conditional_entry_point(
        route_by_step,
        {
            "greeting": "greeting",
            "collect_intent": "collect_intent",
            "collect_shipping": "collect_shipping",
            "fetch_carts": "fetch_carts",
            "select_cart": "select_cart",
            "cart_signature_waiting": "cart_signature_waiting",
            "select_credential_provider": "select_credential_provider",
            "select_payment_method": "select_payment_method",
            "step_up_auth": "step_up_auth",
            "webauthn_auth": "webauthn_auth",
            "execute_payment": "execute_payment",
            "completed": "completed",
            "error": "error",
        }
    )

    # ノードからの遷移
    # 各ノードは next_step に基づいて遷移するか、ENDで終了
    def route_from_node(state: ShoppingFlowState) -> str:
        next_step = state.get("next_step")
        if next_step and next_step != END:
            return next_step
        return END

    # 全ノードに共通のルーティングを適用
    for node_name in ["greeting", "collect_intent", "collect_shipping", "fetch_carts",
                      "select_cart", "cart_signature_waiting", "select_credential_provider",
                      "select_payment_method", "step_up_auth", "webauthn_auth", "execute_payment"]:
        workflow.add_conditional_edges(
            node_name,
            route_from_node,
            {
                "fetch_carts": "fetch_carts",
                "step_up_auth": "step_up_auth",
                "webauthn_auth": "webauthn_auth",
                "execute_payment": "execute_payment",
                "completed": "completed",
                "error": "error",
                END: END
            }
        )

    # 終端ノード
    workflow.add_edge("completed", END)
    workflow.add_edge("error", END)

    # コンパイル
    compiled = workflow.compile()

    logger.info("[create_shopping_flow_graph] LangGraph shopping flow compiled successfully (13 nodes)")

    return compiled
