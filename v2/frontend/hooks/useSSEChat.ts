"use client";

/**
 * v2/frontend/hooks/useSSEChat.ts
 *
 * SSEチャットフック（AP2仕様準拠 + JWT認証）
 *
 * AP2要件:
 * - JWTをAuthorizationヘッダーに追加
 * - payer_email = JWT.email
 */

import { useState, useCallback, useRef } from "react";
import { ChatMessage, ChatSSEEvent, SignatureRequestEvent, Product } from "@/lib/types/chat";
import { getAuthHeaders } from "@/lib/passkey";

export function useSSEChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentAgentMessage, setCurrentAgentMessage] = useState("");
  const [currentAgentThinking, setCurrentAgentThinking] = useState(""); // LLMの思考内容
  const [signatureRequest, setSignatureRequest] = useState<SignatureRequestEvent | null>(null);
  const [currentProducts, setCurrentProducts] = useState<Product[]>([]);
  const [currentCartCandidates, setCurrentCartCandidates] = useState<any[]>([]);

  // 新しいリッチコンテンツ用のstate
  const [credentialProviders, setCredentialProviders] = useState<any[]>([]);
  const [shippingFormRequest, setShippingFormRequest] = useState<any | null>(null);
  const [paymentMethods, setPaymentMethods] = useState<any[]>([]);
  const [webauthnRequest, setWebauthnRequest] = useState<any | null>(null);
  const [paymentCompletedInfo, setPaymentCompletedInfo] = useState<any | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  // セッションIDを管理（会話を通じて同じIDを使用）
  const sessionIdRef = useRef<string>(`session_${Date.now()}_${Math.random().toString(36).substring(7)}`);

  const sendMessage = useCallback(async (userInput: string) => {
    // 特殊なトークンの場合はユーザーメッセージを表示しない
    const isInternalTrigger = userInput.startsWith("_");

    // ユーザーメッセージを追加（内部トリガーの場合はスキップ）
    if (!isInternalTrigger) {
      const userMessage: ChatMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: userInput,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMessage]);
    }

    // ストリーミング開始
    setIsStreaming(true);

    // リッチコンテンツは即座にクリア（次の応答で上書きされる想定）
    setCredentialProviders([]);
    setShippingFormRequest(null);
    setPaymentMethods([]);
    setWebauthnRequest(null);
    setPaymentCompletedInfo(null);

    // AbortController作成
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    try {
      // 環境変数から直接Shopping Agent URLを取得
      const shoppingAgentUrl = process.env.NEXT_PUBLIC_SHOPPING_AGENT_URL || "http://localhost:8000";

      // AP2準拠: JWTをAuthorizationヘッダーに追加
      const authHeaders = getAuthHeaders();

      const response = await fetch(`${shoppingAgentUrl}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders,  // JWT Authorization header
        },
        body: JSON.stringify({
          user_input: userInput,
          session_id: sessionIdRef.current,  // セッションIDを含める
        }),
        signal: abortController.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error("Response body is null");
      }

      let buffer = "";
      let agentMessageContent = "";
      let agentThinkingContent = ""; // LLMの思考過程を蓄積
      let streamProducts: Product[] = []; // ローカル変数で商品データを管理
      let streamCartCandidates: any[] = []; // ローカル変数でカート候補を管理
      let hasReceivedContentEvent = false; // リッチコンテンツイベント受信フラグ
      let isThinking = false; // LLMが思考中かどうか
      let isTyping = false; // テキストをタイプ中かどうか

      while (true) {
        const { done, value } = await reader.read();

        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            let data = line.slice(6).trim();

            if (!data) continue;

            // 二重の "data: " プレフィックスを処理
            if (data.startsWith("data: ")) {
              data = data.slice(6).trim();
            }

            try {
              const event: ChatSSEEvent = JSON.parse(data);

              // デバッグ：イベントをコンソールに出力
              console.log("[SSE Event]", event.type, {
                hasReceivedContentEvent,
                currentCartCandidatesCount: streamCartCandidates.length,
                event
              });

              switch (event.type) {
                case "agent_thinking":
                  // LLMの思考過程をリアルタイム表示
                  if (!isThinking) {
                    isThinking = true;
                    // 思考開始のマーカーを表示
                    agentThinkingContent = "🤔 思考中...\n\n";
                  }
                  agentThinkingContent += event.content || "";
                  // 思考内容を専用stateに保存
                  setCurrentAgentThinking(agentThinkingContent);
                  break;

                case "agent_thinking_complete":
                  // LLM思考完了 - 思考内容をクリア
                  isThinking = false;
                  agentThinkingContent = "";
                  setCurrentAgentThinking("");
                  break;

                case "agent_text_chunk":
                  // エージェント応答のストリーミングチャンク
                  if (!isTyping) {
                    isTyping = true;
                    agentMessageContent = "";
                  }
                  agentMessageContent += event.content || "";
                  setCurrentAgentMessage(agentMessageContent);
                  break;

                case "agent_text_complete":
                  // エージェント応答完了
                  isTyping = false;
                  break;

                case "agent_text":
                  // リッチコンテンツイベントを受信していない場合のみクリア
                  if (!hasReceivedContentEvent) {
                    setCurrentProducts([]);
                    setCurrentCartCandidates([]);
                    setCurrentAgentMessage("");
                  }
                  agentMessageContent += event.content;
                  setCurrentAgentMessage(agentMessageContent);
                  break;

                case "signature_request":
                  // 署名リクエストを保存
                  // mandate_typeがない場合、mandate.typeから推測
                  const signatureEvent = event as any;
                  if (!signatureEvent.mandate_type && signatureEvent.mandate?.type) {
                    const mandateType = signatureEvent.mandate.type;
                    if (mandateType === "IntentMandate") {
                      signatureEvent.mandate_type = "intent";
                    } else if (mandateType === "CartMandate") {
                      signatureEvent.mandate_type = "cart";
                    } else if (mandateType === "PaymentMandate") {
                      signatureEvent.mandate_type = "payment";
                    }
                  }
                  setSignatureRequest(signatureEvent);
                  break;

                case "product_list":
                  // 商品リストを保存（ローカル変数 + state）
                  streamProducts = event.products;
                  // 新しい商品リストで直接置き換え（空配列を経由しない）
                  setCurrentProducts(streamProducts);
                  setCurrentCartCandidates([]);
                  agentMessageContent = `\n\n${event.products.length}件の商品が見つかりました：`;
                  setCurrentAgentMessage(agentMessageContent);
                  hasReceivedContentEvent = true; // リッチコンテンツイベントを受信
                  break;

                case "cart_options":
                  // AP2/A2A仕様準拠：カート候補を表示
                  const cartEvent = event as any;
                  streamCartCandidates = cartEvent.items || [];
                  // 新しいカート候補で直接置き換え（空配列を経由しない）
                  setCurrentProducts([]);
                  setCurrentCartCandidates(streamCartCandidates);
                  agentMessageContent = "";
                  setCurrentAgentMessage(agentMessageContent);
                  hasReceivedContentEvent = true; // リッチコンテンツイベントを受信
                  break;

                case "credential_provider_selection":
                  // Credential Provider選択リクエスト
                  const cpEvent = event as any;
                  setCredentialProviders(cpEvent.providers || []);
                  break;

                case "shipping_form_request":
                  // 配送先フォームリクエスト
                  const shippingEvent = event as any;
                  setShippingFormRequest(shippingEvent.form_schema);
                  break;

                case "payment_method_selection":
                  // 支払い方法選択リクエスト
                  const paymentEvent = event as any;
                  setPaymentMethods(paymentEvent.payment_methods || []);
                  break;

                case "payment_completed":
                  // AP2完全準拠: 決済完了情報
                  const paymentCompletedEvent = event as any;
                  setPaymentCompletedInfo({
                    transaction_id: paymentCompletedEvent.transaction_id,
                    product_name: paymentCompletedEvent.product_name,
                    amount: paymentCompletedEvent.amount,
                    currency: paymentCompletedEvent.currency,
                    merchant_name: paymentCompletedEvent.merchant_name,
                    receipt_url: paymentCompletedEvent.receipt_url,
                    status: paymentCompletedEvent.status,
                  });
                  console.log("[Payment Completed]", paymentCompletedEvent);
                  break;

                case "webauthn_request":
                  // WebAuthn認証リクエスト
                  const webauthnEvent = event as any;
                  setWebauthnRequest({
                    challenge: webauthnEvent.challenge,
                    rp_id: webauthnEvent.rp_id,
                    timeout: webauthnEvent.timeout,
                  });
                  break;

                case "stepup_authentication_request":
                  // AP2完全準拠: 3D Secure 2.0認証リクエスト
                  const stepupAuthEvent = event as any;
                  const stepupContent = stepupAuthEvent.content || stepupAuthEvent;
                  const stepupMethod = stepupContent.stepup_method || "3ds2";
                  const challengeUrl = stepupContent.challenge_url;

                  console.log("[3DS Authentication Request]", {
                    stepupMethod,
                    challengeUrl,
                    paymentMethodId: stepupContent.payment_method_id,
                    fullEvent: stepupAuthEvent
                  });

                  // 3DS認証画面を新しいウィンドウで開く
                  const threeDSWindow = window.open(
                    challengeUrl,
                    "ap2_3ds_auth",
                    "width=600,height=700,scrollbars=yes,resizable=yes"
                  );

                  if (!threeDSWindow) {
                    console.error("Failed to open 3DS window. Please allow pop-ups.");
                    agentMessageContent += "\n\n❌ ポップアップがブロックされました。ブラウザの設定でポップアップを許可してください。";
                    setCurrentAgentMessage(agentMessageContent);
                  } else {
                    // ウィンドウが閉じられるのを監視
                    const check3DSWindowClosed = setInterval(() => {
                      if (threeDSWindow.closed) {
                        clearInterval(check3DSWindowClosed);
                        console.log("[3DS Window] Closed");

                        // 3DS認証完了後、フローを継続
                        sendMessage("3ds-completed");
                      }
                    }, 500);
                  }
                  break;

                case "step_up_redirect":
                  // AP2 Step 13: Step-upリダイレクト
                  const stepUpEvent = event as any;
                  const stepUpUrl = stepUpEvent.step_up_url;
                  const stepUpSessionId = stepUpEvent.session_id;

                  console.log("[Step-up Redirect]", {
                    stepUpUrl,
                    stepUpSessionId,
                    reason: stepUpEvent.reason
                  });

                  // 新しいウィンドウでStep-up画面を開く
                  const stepUpWindow = window.open(
                    stepUpUrl,
                    "ap2_step_up",
                    "width=600,height=800,scrollbars=yes,resizable=yes"
                  );

                  if (!stepUpWindow) {
                    console.error("Failed to open step-up window. Please allow pop-ups.");
                    agentMessageContent += "\n\n❌ ポップアップがブロックされました。ブラウザの設定でポップアップを許可してください。";
                    setCurrentAgentMessage(agentMessageContent);
                  } else {
                    // ウィンドウが閉じられるのを監視
                    const checkWindowClosed = setInterval(() => {
                      if (stepUpWindow.closed) {
                        clearInterval(checkWindowClosed);
                        console.log("[Step-up Window] Closed");

                        // Step-up完了のコールバックを送信
                        // URLパラメータからステータスを取得できるようにする
                        const urlParams = new URLSearchParams(window.location.search);
                        const stepUpStatus = urlParams.get("step_up_status");

                        if (stepUpStatus === "success") {
                          // Step-up成功時の処理
                          console.log("[Step-up] Success callback");
                          // フロー続行のために次のメッセージを送信
                          sendMessage("step-up completed");
                        } else if (stepUpStatus === "cancelled") {
                          // キャンセル時の処理
                          console.log("[Step-up] Cancelled");
                          agentMessageContent += "\n\n認証がキャンセルされました。別の支払い方法を選択してください。";
                          setCurrentAgentMessage(agentMessageContent);
                        }
                      }
                    }, 500);
                  }
                  break;

                case "done":
                  // エージェントメッセージを確定
                  if (agentMessageContent) {
                    const agentMessage: ChatMessage = {
                      id: `agent-${Date.now()}`,
                      role: "agent",
                      content: agentMessageContent,
                      timestamp: new Date(),
                      // ローカル変数のstreamProductsを使用（状態更新のタイミングに依存しない）
                      metadata: streamProducts.length > 0 ? { products: streamProducts } : undefined,
                    };
                    setMessages((prev) => [...prev, agentMessage]);
                  }
                  setCurrentAgentMessage("");
                  setIsStreaming(false);
                  break;

                case "error":
                  console.error("Agent error:", event.message);
                  const errorMessage: ChatMessage = {
                    id: `agent-error-${Date.now()}`,
                    role: "agent",
                    content: `エラー: ${event.message}`,
                    timestamp: new Date(),
                  };
                  setMessages((prev) => [...prev, errorMessage]);
                  setCurrentAgentMessage("");
                  setIsStreaming(false);
                  break;
              }
            } catch (e) {
              console.error("Failed to parse SSE event:", e, "Data:", data);
            }
          }
        }
      }
    } catch (error: any) {
      if (error.name === "AbortError") {
        console.log("Request aborted");
      } else {
        console.error("Error in SSE chat:", error);
        setMessages((prev) => [
          ...prev,
          {
            id: `error-${Date.now()}`,
            role: "agent",
            content: "申し訳ございません。エラーが発生しました。",
            timestamp: new Date(),
          },
        ]);
      }
      setIsStreaming(false);
      setCurrentAgentMessage("");
    }
  }, []);

  const clearSignatureRequest = useCallback(() => {
    setSignatureRequest(null);
  }, []);

  const clearWebauthnRequest = useCallback(() => {
    setWebauthnRequest(null);
  }, []);

  const addMessage = useCallback((message: ChatMessage) => {
    setMessages((prev) => [...prev, message]);
  }, []);

  const stopStreaming = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
    // currentAgentMessageとcurrentProductsはそのまま残す（次のメッセージ送信時にクリア）
  }, []);

  // セッションIDを外部から設定できる関数（AP2 Step-up対応）
  const setSessionId = useCallback((newSessionId: string) => {
    sessionIdRef.current = newSessionId;
    console.log("[useSSEChat] Session ID updated:", newSessionId);
  }, []);

  return {
    messages,
    isStreaming,
    currentAgentMessage,
    currentAgentThinking,  // LLMの思考内容を公開
    currentProducts,
    currentCartCandidates,
    signatureRequest,
    credentialProviders,
    shippingFormRequest,
    paymentMethods,
    webauthnRequest,
    paymentCompletedInfo,  // 決済完了情報
    sessionId: sessionIdRef.current,
    sendMessage,
    addMessage,
    clearSignatureRequest,
    clearWebauthnRequest,
    stopStreaming,
    setSessionId,  // セッションID設定関数を公開
  };
}
