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
import type { A2UIComponent } from "@/lib/types/a2ui";
import { applyDataModelOperation } from "@/lib/a2ui/jsonPointer";
import { buildUserAction, serializeUserAction } from "@/lib/a2ui/userAction";

/**
 * A2UI v0.9 Surface State
 * Represents a managed UI surface with components and data model
 */
export interface A2UISurfaceState {
  surfaceId: string;
  catalogId?: string;
  components: A2UIComponent[];
  dataModel: Record<string, any>;
}

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
  const [paymentMethods, setPaymentMethods] = useState<any[]>([]);
  const [webauthnRequest, setWebauthnRequest] = useState<any | null>(null);
  const [paymentCompletedInfo, setPaymentCompletedInfo] = useState<any | null>(null);

  // A2UI v0.9: サーフェス管理用のstate
  const [a2uiSurfaces, setA2UISurfaces] = useState<Map<string, A2UISurfaceState>>(new Map());

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
    setPaymentMethods([]);
    setWebauthnRequest(null);
    setPaymentCompletedInfo(null);

    // A2UIサーフェスもクリア（新しいメッセージ送信時に前のUIを消す）
    setA2UISurfaces(new Map());

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
      let paymentCompletedData: any = null; // 決済完了情報（AP2完全準拠）
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
                    // 新しいメッセージの開始
                    isTyping = true;
                    agentMessageContent = "";
                    console.log("[agent_text_chunk] Starting new message");
                  }
                  agentMessageContent += event.content || "";
                  setCurrentAgentMessage(agentMessageContent);
                  break;

                case "agent_text_complete":
                  // エージェント応答完了
                  // AP2完全準拠: agent_text_completeイベントには完成したメッセージ全体が含まれる
                  const completeEvent = event as any;
                  const completeMessage = completeEvent.content || "";

                  console.log("[agent_text_complete]", {
                    eventContent: completeMessage,
                    length: completeMessage.length
                  });

                  // agent_text_completeではメッセージを追加しない
                  // doneイベントで一括してメッセージとメタデータを追加する
                  // ただし、agentMessageContentにコンテンツを設定
                  if (completeMessage.trim()) {
                    agentMessageContent = completeMessage;
                  }

                  // currentAgentMessageをクリア（ストリーミング表示を終了）
                  setCurrentAgentMessage("");
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
                  console.log("[SSE cart_options] Received cart candidates:", {
                    itemCount: streamCartCandidates.length,
                    items: streamCartCandidates,
                    firstItem: streamCartCandidates[0]
                  });
                  // 新しいカート候補で直接置き換え（空配列を経由しない）
                  setCurrentProducts([]);
                  console.log("[SSE cart_options] Setting currentCartCandidates with:", streamCartCandidates.length, "items");
                  setCurrentCartCandidates(streamCartCandidates);
                  agentMessageContent = "";
                  setCurrentAgentMessage(agentMessageContent);
                  hasReceivedContentEvent = true; // リッチコンテンツイベントを受信
                  console.log("[SSE cart_options] hasReceivedContentEvent set to true");
                  break;

                case "credential_provider_selection":
                  // Credential Provider選択リクエスト（A2UIに移行済み - stateは更新しない）
                  // const cpEvent = event as any;
                  // setCredentialProviders(cpEvent.providers || []);
                  console.log("[SSE] credential_provider_selection event received (ignored, using A2UI)");
                  break;

                // Note: shipping_form_request is deprecated, use A2UI surfaces instead

                case "payment_method_selection":
                  // 支払い方法選択リクエスト（A2UIに移行済み - stateは更新しない）
                  // const paymentEvent = event as any;
                  // setPaymentMethods(paymentEvent.payment_methods || []);
                  console.log("[SSE] payment_method_selection event received (ignored, using A2UI)");
                  break;

                case "payment_completed":
                  // AP2完全準拠: 決済完了情報
                  const paymentCompletedEvent = event as any;
                  paymentCompletedData = {
                    transaction_id: paymentCompletedEvent.transaction_id,
                    product_name: paymentCompletedEvent.product_name,
                    amount: paymentCompletedEvent.amount,
                    currency: paymentCompletedEvent.currency,
                    merchant_name: paymentCompletedEvent.merchant_name,
                    receipt_url: paymentCompletedEvent.receipt_url,
                    status: paymentCompletedEvent.status,
                  };
                  // stateにも保存（従来の互換性のため）
                  setPaymentCompletedInfo(paymentCompletedData);
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

                // A2UI v0.9 Protocol Messages
                case "a2ui_create_surface":
                  // createSurface: 新しいサーフェスを初期化
                  const createEvent = event as any;
                  console.log("[A2UI v0.9] createSurface", {
                    surfaceId: createEvent.surface_id,
                    catalogId: createEvent.catalog_id
                  });
                  setA2UISurfaces(prev => {
                    const next = new Map(prev);
                    next.set(createEvent.surface_id, {
                      surfaceId: createEvent.surface_id,
                      catalogId: createEvent.catalog_id,
                      components: [],
                      dataModel: {}
                    });
                    return next;
                  });
                  break;

                case "a2ui_update_components":
                  // updateComponents: コンポーネント定義を更新
                  const componentsEvent = event as any;
                  console.log("[A2UI v0.9] updateComponents", {
                    surfaceId: componentsEvent.surface_id,
                    componentCount: componentsEvent.components?.length || 0
                  });
                  setA2UISurfaces(prev => {
                    const next = new Map(prev);
                    const surface = next.get(componentsEvent.surface_id);
                    if (surface) {
                      next.set(componentsEvent.surface_id, {
                        ...surface,
                        components: componentsEvent.components || []
                      });
                    }
                    return next;
                  });
                  break;

                case "a2ui_update_data_model":
                  // updateDataModel: データモデルを更新
                  const dataModelEvent = event as any;
                  console.log("[A2UI v0.9] updateDataModel", {
                    surfaceId: dataModelEvent.surface_id,
                    path: dataModelEvent.path,
                    op: dataModelEvent.op
                  });
                  setA2UISurfaces(prev => {
                    const next = new Map(prev);
                    const surface = next.get(dataModelEvent.surface_id);
                    if (surface) {
                      // Apply JSON Pointer operation (RFC 6901 compliant)
                      const updatedDataModel = applyDataModelOperation(
                        surface.dataModel,
                        dataModelEvent.op,
                        dataModelEvent.path,
                        dataModelEvent.value
                      );
                      next.set(dataModelEvent.surface_id, {
                        ...surface,
                        dataModel: updatedDataModel
                      });
                    }
                    return next;
                  });
                  break;

                case "a2ui_delete_surface":
                  // deleteSurface: サーフェスを削除
                  const deleteEvent = event as any;
                  console.log("[A2UI v0.9] deleteSurface", {
                    surfaceId: deleteEvent.surface_id
                  });
                  setA2UISurfaces(prev => {
                    const next = new Map(prev);
                    next.delete(deleteEvent.surface_id);
                    return next;
                  });
                  break;

                case "done":
                  // エージェントメッセージを確定
                  console.log("[SSE Done Event] agentMessageContent:", agentMessageContent);
                  console.log("[SSE Done Event] paymentCompletedData:", paymentCompletedData);
                  console.log("[SSE Done Event] streamProducts:", streamProducts);
                  console.log("[SSE Done Event] streamCartCandidates:", streamCartCandidates);

                  // agent_text_completeで既に確定されていない場合のみ追加
                  if (agentMessageContent.trim()) {
                    // メタデータを構築（AP2完全準拠）
                    const metadata: any = {};

                    // 商品リストがある場合
                    if (streamProducts.length > 0) {
                      metadata.products = streamProducts;
                    }

                    // カート候補がある場合（メッセージに含めて表示）
                    if (streamCartCandidates.length > 0) {
                      metadata.cart_candidates = streamCartCandidates;
                      console.log("[SSE Done Event] Adding cart_candidates to metadata:", metadata.cart_candidates.length, "items");
                    }

                    // 決済完了情報がある場合
                    if (paymentCompletedData) {
                      metadata.payment_result = paymentCompletedData;
                      console.log("[SSE Done Event] Adding payment_result to metadata:", metadata.payment_result);
                    } else {
                      console.log("[SSE Done Event] No payment_result found");
                    }

                    console.log("[SSE Done Event] Final metadata:", metadata);

                    const agentMessage: ChatMessage = {
                      id: `agent-${Date.now()}`,
                      role: "agent",
                      content: agentMessageContent,
                      timestamp: new Date(),
                      metadata: Object.keys(metadata).length > 0 ? metadata : undefined,
                    };
                    console.log("[SSE Done Event] Final message:", agentMessage);
                    setMessages((prev) => [...prev, agentMessage]);
                  }

                  // ストリーミング終了後、カート候補をクリア（メッセージに含まれているため）
                  if (streamCartCandidates.length > 0) {
                    setCurrentCartCandidates([]);
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

  /**
   * A2UI v0.9: Send a userAction message
   *
   * A2UI v0.9 Specification:
   * - userAction.context contains RESOLVED VALUES (not path references)
   * - Client resolves all values before sending
   * - Server receives ready-to-use values
   *
   * @param actionName - The action name (e.g., "submit_shipping", "select_credential_provider")
   * @param surfaceId - The surface ID where the action originated
   * @param sourceComponentId - The component ID that triggered the action
   * @param context - Resolved context values (already resolved from paths/literals)
   * @param displayMessage - Optional message to display in chat UI
   */
  const sendUserAction = useCallback(async (
    actionName: string,
    surfaceId: string,
    sourceComponentId: string,
    context: Record<string, any>,
    displayMessage?: string
  ) => {
    // Build A2UI v0.9 compliant userAction with resolved context
    const userAction = buildUserAction(
      actionName,
      surfaceId,
      sourceComponentId,
      context
    );
    const serialized = serializeUserAction(userAction);

    console.log("[A2UI v0.9] Sending userAction:", userAction.userAction);

    // Send A2UI message
    await sendMessage(serialized);

    // If a display message is provided, add it to the chat UI
    if (displayMessage) {
      const userMessage: ChatMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: displayMessage,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMessage]);
    }
  }, [sendMessage]);

  // A2UI v0.9: サーフェスをクリアする関数
  const clearA2UISurfaces = useCallback(() => {
    setA2UISurfaces(new Map());
  }, []);

  // A2UI v0.9: 特定のサーフェスを取得する関数
  const getA2UISurface = useCallback((surfaceId: string): A2UISurfaceState | undefined => {
    return a2uiSurfaces.get(surfaceId);
  }, [a2uiSurfaces]);

  // A2UI v0.9: ローカルでdataModelを更新する関数（two-way binding用）
  const updateSurfaceDataModel = useCallback((surfaceId: string, path: string, value: any) => {
    setA2UISurfaces(prev => {
      const next = new Map(prev);
      const surface = next.get(surfaceId);
      if (surface) {
        // Apply the update using JSON Pointer
        const updatedDataModel = applyDataModelOperation(
          surface.dataModel,
          "replace",
          path,
          value
        );
        next.set(surfaceId, {
          ...surface,
          dataModel: updatedDataModel
        });
      }
      return next;
    });
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
    paymentMethods,
    webauthnRequest,
    paymentCompletedInfo,  // 決済完了情報
    sessionId: sessionIdRef.current,
    // A2UI v0.9: サーフェス管理
    a2uiSurfaces,  // Map<surfaceId, A2UISurfaceState>
    getA2UISurface,  // 特定のサーフェスを取得
    clearA2UISurfaces,  // 全サーフェスをクリア
    updateSurfaceDataModel,  // ローカルdataModel更新（two-way binding用）
    // 関数群
    sendMessage,
    sendUserAction,  // A2UI v0.9: userActionメッセージ送信
    addMessage,
    clearSignatureRequest,
    clearWebauthnRequest,
    stopStreaming,
    setSessionId,  // セッションID設定関数を公開
  };
}
