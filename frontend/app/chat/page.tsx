"use client";

/**
 * v2/frontend/app/chat/page.tsx
 *
 * チャット画面（AP2仕様準拠 + JWT認証統合）
 *
 * AP2要件:
 * - JWTによるHTTPセッション認証（Layer 1）
 * - マンデート署名（WebAuthn/Passkey）（Layer 2）
 * - payer_email = JWT.email（オプション）
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useSSEChat } from "@/hooks/useSSEChat";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { ChatInput } from "@/components/chat/ChatInput";
import { SignaturePromptModal } from "@/components/chat/SignaturePromptModal";
import { PasskeyRegistration } from "@/components/auth/PasskeyRegistration";
import { PasskeyAuthentication } from "@/components/auth/PasskeyAuthentication";
import { ProductCarousel } from "@/components/product/ProductCarousel";
import { CartCarousel } from "@/components/cart/CartCarousel";
import { CartDetailsModal } from "@/components/cart/CartDetailsModal";
import { A2UISurfaceRenderer } from "@/components/a2ui/A2UISurfaceRenderer";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent } from "@/components/ui/card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Bot, LogOut, User } from "lucide-react";
import { Product } from "@/lib/types/chat";
import type { A2UIAction } from "@/lib/types/a2ui";
import {
  isAuthenticated,
  getCurrentUser,
  logout,
  getAuthHeaders,
  getAccessToken,
  isCredentialProviderPasskeyRegistered
} from "@/lib/passkey";

export default function ChatPage() {
  const router = useRouter();
  const {
    messages,
    isStreaming,
    currentAgentMessage,
    currentAgentThinking,  // LLMの思考内容
    currentProducts,
    currentCartCandidates,
    signatureRequest,
    // credentialProviders,  // A2UIに移行済み
    // paymentMethods,  // A2UIに移行済み
    webauthnRequest,
    sessionId,
    sendMessage,
    sendUserAction,  // A2UI v0.9: userActionメッセージ送信
    addMessage,
    clearSignatureRequest,
    clearWebauthnRequest,
    stopStreaming,
    setSessionId,  // AP2 Step-up対応：セッションID設定関数
    paymentCompletedInfo,  // 決済完了情報
    // A2UI v0.9: サーフェス管理
    a2uiSurfaces,
    updateSurfaceDataModel,
    clearA2UISurfaces,
  } = useSSEChat();

  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const [isPasskeyRegistered, setIsPasskeyRegistered] = useState(false);
  const [showPasskeyRegistration, setShowPasskeyRegistration] = useState(false);
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState<any>(null);
  const [cart, setCart] = useState<Product[]>([]);
  const [selectedCartForDetails, setSelectedCartForDetails] = useState<any | null>(null);

  // A2UI v0.9: アクションハンドラー（ボタンクリック等）
  // A2UI v0.9仕様: contextには解決済みの値を送信
  const handleA2UIAction = useCallback((action: A2UIAction, surfaceId: string, sourceComponentId: string) => {
    console.log("[A2UI] Action triggered:", { action, surfaceId, sourceComponentId });

    // Get the current surface's dataModel for path resolution
    const surface = a2uiSurfaces.get(surfaceId);
    if (!surface) {
      console.warn("[A2UI] Surface not found:", surfaceId);
      return;
    }

    // Resolve all context values (both path refs and literals)
    // A2UI v0.9: Client resolves values before sending
    const resolvedContext: Record<string, any> = {};

    if (action.context) {
      for (const [key, value] of Object.entries(action.context)) {
        if (value && typeof value === "object") {
          if ("path" in value && value.path) {
            // Path reference - resolve from dataModel
            const path = value.path as string;
            const parts = path.replace(/^\//, "").split("/");
            let resolved: any = surface.dataModel;
            for (const part of parts) {
              if (resolved && typeof resolved === "object" && part in resolved) {
                resolved = resolved[part];
              } else {
                resolved = undefined;
                break;
              }
            }
            resolvedContext[key] = resolved;
          } else if ("literalNumber" in value) {
            // Literal number - use directly
            resolvedContext[key] = value.literalNumber;
          } else if ("literalString" in value) {
            // Literal string - use directly
            resolvedContext[key] = value.literalString;
          } else if ("literalBoolean" in value) {
            // Literal boolean - use directly
            resolvedContext[key] = value.literalBoolean;
          }
        }
      }
    }

    // Send userAction with resolved context (A2UI v0.9 compliant)
    sendUserAction(
      action.name,
      surfaceId,
      sourceComponentId,
      resolvedContext,
      `${action.name}を実行しました`
    );
  }, [a2uiSurfaces, sendUserAction]);

  // A2UI v0.9: データモデル更新ハンドラー（two-way binding + バリデーション）
  const handleDataModelChange = useCallback((surfaceId: string) => {
    return (path: string, value: any) => {
      // Update the field value
      updateSurfaceDataModel(surfaceId, path, value);

      // Run validation after field update
      const surface = a2uiSurfaces.get(surfaceId);
      if (surface && surface.dataModel._validation?.requiredFields) {
        const requiredFields = surface.dataModel._validation.requiredFields as string[];
        const shipping = surface.dataModel.shipping || {};

        // Calculate new shipping values (apply the current change)
        const fieldName = path.replace("/shipping/", "");
        const newShipping = { ...shipping, [fieldName]: value };

        // Check if all required fields are filled
        const formInvalid = requiredFields.some(
          (field: string) => !newShipping[field] || newShipping[field].trim() === ""
        );

        // Update formInvalid
        updateSurfaceDataModel(surfaceId, "/formInvalid", formInvalid);
      }
    };
  }, [updateSurfaceDataModel, a2uiSurfaces]);

  // AP2完全準拠: Credential Provider用Passkeyは専用画面で登録
  // /auth/register-passkeyへリダイレクト

  // AP2準拠: JWT認証チェック（Layer 1）
  useEffect(() => {
    // JWT認証状態をチェック
    if (!isAuthenticated()) {
      // 未認証の場合はログイン画面へリダイレクト
      router.push('/auth/login');
      return;
    }

    // 現在のユーザー情報を取得
    const user = getCurrentUser();
    if (user) {
      setCurrentUser(user);
      setCurrentUserId(user.id);
      setIsPasskeyRegistered(true);

      // レガシーのlocalStorageキーも設定（既存コンポーネントとの互換性）
      localStorage.setItem("ap2_user_id", user.id);

      // sessionStorageにもuser_idを保存（支払い方法管理用）
      sessionStorage.setItem("user_id", user.id);

      // AP2完全準拠: Credential Provider用Passkeyの登録チェック（Mandate署名用）
      // Shopping Agentはメール/パスワード認証、Credential ProviderはPasskey認証
      if (!isCredentialProviderPasskeyRegistered()) {
        // Passkey未登録の場合は登録画面へリダイレクト
        router.push('/auth/register-passkey');
      }
    }
  }, [router]);

  // ログアウト処理
  const handleLogout = () => {
    logout();
    router.push('/auth/login');
  };

  // AP2完全準拠: Credential Provider用Passkeyは専用画面(/auth/register-passkey)で登録

  // Step-up認証完了のコールバックをチェック
  useEffect(() => {
    // AP2完全準拠: Step-up認証完了後のコールバック処理
    // Step-upから戻ってきたときは window.location.href でページが完全にリロードされるため、
    // このuseEffectはマウント時（依存配列[]）のみ実行すればよい
    const urlParams = new URLSearchParams(window.location.search);
    const stepUpStatus = urlParams.get("step_up_status");
    const stepUpSessionId = urlParams.get("step_up_session_id");
    const sessionId = urlParams.get("session_id");

    console.log("[Step-up Callback] Checking URL params:", {
      stepUpStatus,
      stepUpSessionId,
      sessionId,
      fullUrl: window.location.href
    });

    if (stepUpStatus && stepUpSessionId && sessionId) {
      console.log("[Step-up Callback] Detected:", { stepUpStatus, stepUpSessionId, sessionId });

      // AP2準拠：return_urlから取得したsession_idを使用
      // これにより、Step-up前のセッションに戻れる
      setSessionId(sessionId);

      // URLパラメータをクリーンアップ
      const cleanUrl = window.location.pathname;
      window.history.replaceState({}, document.title, cleanUrl);

      if (stepUpStatus === "success") {
        // Step-up成功 - Shopping Agentに完了を通知
        // AP2準拠: 内部トリガーとして送信（ユーザーメッセージとして表示しない）
        console.log("[Step-up] Success - sending completion message to agent with session_id:", sessionId);
        setTimeout(() => {
          console.log("[Step-up] About to send message: _step-up-completed:" + stepUpSessionId);
          sendMessage(`_step-up-completed:${stepUpSessionId}`);
        }, 500);
      } else if (stepUpStatus === "cancelled") {
        // キャンセル - ユーザーに通知
        console.log("[Step-up] Cancelled");
        setTimeout(() => {
          sendMessage("認証をキャンセルしました。別の支払い方法を選択してください。");
        }, 500);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // マウント時のみ実行（Step-upからのリダイレクトでページがリロードされる）

  // メッセージが追加されたら自動スクロール
  useEffect(() => {
    if (scrollAreaRef.current) {
      const scrollElement = scrollAreaRef.current.querySelector(
        "[data-radix-scroll-area-viewport]"
      );
      if (scrollElement) {
        scrollElement.scrollTop = scrollElement.scrollHeight;
      }
    }
  }, [messages, currentAgentMessage]);

  // Passkey登録完了
  const handlePasskeyRegistered = (userId: string, userName: string) => {
    localStorage.setItem("ap2_passkey_registered", "true");
    localStorage.setItem("ap2_user_id", userId);
    localStorage.setItem("ap2_user_name", userName);
    setIsPasskeyRegistered(true);
    setCurrentUserId(userId);
    setShowPasskeyRegistration(false);
  };

  // カート追加（商品選択）
  const handleAddToCart = (product: Product) => {
    setCart((prev) => {
      const existing = prev.find((p) => p.id === product.id);
      if (existing) {
        return prev; // 既に追加済み
      }
      return [...prev, product];
    });

    // エージェントに商品IDを送信
    sendMessage(product.id);
  };

  // カート候補選択
  const handleSelectCart = (cartCandidate: any) => {
    console.log("Cart selected:", cartCandidate);
    // AP2準拠：カートIDをcontents.idから取得
    const cartId = cartCandidate.cart_mandate.contents.id;
    // カートIDをエージェントに送信
    sendMessage(cartId);
  };

  // カート詳細表示
  const handleViewCartDetails = (cartCandidate: any) => {
    setSelectedCartForDetails(cartCandidate);
  };

  // 署名処理
  const handleSign = async (attestation: any) => {
    console.log("Signature completed:", attestation);

    try {
      if (!signatureRequest) return;

      const shoppingAgentUrl = process.env.NEXT_PUBLIC_SHOPPING_AGENT_URL || "http://localhost:8000";

      // AP2仕様準拠: CartMandate署名とその他の署名を分ける
      if (signatureRequest.mandate_type === "cart") {
        // CartMandate署名: POST /cart/submit-signature
        console.log("Submitting CartMandate signature to Shopping Agent:", {
          session_id: sessionId,
          cart_mandate: signatureRequest.mandate,
          webauthn_assertion: attestation,
        });

        // AP2準拠: JWT認証ヘッダーを追加（Layer 1）
        const authHeaders = getAuthHeaders();
        const response = await fetch(`${shoppingAgentUrl}/cart/submit-signature`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...authHeaders,  // AP2 Layer 1: JWT Authorization
          },
          body: JSON.stringify({
            session_id: sessionId,
            cart_mandate: signatureRequest.mandate,
            webauthn_assertion: attestation,
          }),
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const result = await response.json();
        console.log("CartMandate signature result:", result);

        clearSignatureRequest();

        if (result.status === "success") {
          // AP2仕様準拠: CartMandate署名完了後、自動的にCredential Provider選択へ進む
          // 内部的に空メッセージを送信して次のステップをトリガー（ユーザーには表示されない）
          console.log("CartMandate signature successful - triggering next step automatically");

          // ユーザーメッセージを追加せずに、バックエンドに次のステップをトリガー
          sendMessage("_cart_signature_completed");  // 特殊なトークン
        } else {
          sendMessage("CartMandate署名の処理に失敗しました。");
        }
      } else {
        // PaymentMandate署名: POST /payment/submit-attestation
        console.log("Submitting PaymentMandate signature to Shopping Agent:", {
          session_id: sessionId,
          attestation: attestation,
        });

        // AP2準拠: JWT認証ヘッダーを追加（Layer 1）
        const authHeaders = getAuthHeaders();
        const response = await fetch(`${shoppingAgentUrl}/payment/submit-attestation`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...authHeaders,  // AP2 Layer 1: JWT Authorization
          },
          body: JSON.stringify({
            session_id: sessionId,
            attestation: attestation,
          }),
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const result = await response.json();
        console.log("PaymentMandate signature result:", result);

        clearSignatureRequest();

        if (result.status === "success") {
          // AP2仕様準拠: PaymentMandate署名完了後、決済実行へ進む
          console.log("PaymentMandate signature successful - payment execution");
          // 内部トークンで次のステップをトリガー
          sendMessage("_payment_signature_completed");
        } else {
          sendMessage(`決済処理に失敗しました: ${result.error || "不明なエラー"}`);
        }
      }
    } catch (error: any) {
      console.error("Signature verification error:", error);
      clearSignatureRequest();
      sendMessage("署名処理中にエラーが発生しました。");
    }
  };

  // WebAuthn認証成功時の処理
  const handleWebAuthnAuthenticated = async (attestation: any) => {
    console.log("WebAuthn authentication completed:", attestation);

    try {
      // AP2仕様準拠：POST /payment/submit-attestationにattestationを送信
      const shoppingAgentUrl = process.env.NEXT_PUBLIC_SHOPPING_AGENT_URL || "http://localhost:8000";

      console.log("Submitting attestation to Shopping Agent:", {
        session_id: sessionId,
        attestation: attestation,
      });

      // AP2準拠: JWT認証ヘッダーを追加（Layer 1）
      const authHeaders = getAuthHeaders();
      const response = await fetch(`${shoppingAgentUrl}/payment/submit-attestation`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders,  // AP2 Layer 1: JWT Authorization
        },
        body: JSON.stringify({
          session_id: sessionId,
          attestation: attestation,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      console.log("Payment attestation result:", result);

      // WebAuthn認証ダイアログを閉じる
      clearWebauthnRequest();

      if (result.status === "success") {
        // 決済成功 - 領収書URLを含めたメッセージを追加
        const successMessage = {
          id: `agent-payment-success-${Date.now()}`,
          role: "agent" as const,
          content: `✅ 決済が完了しました！\n\nトランザクションID: ${result.transaction_id}\n商品: ${result.product_name}\n金額: ¥${result.amount?.toLocaleString() || "N/A"}`,
          timestamp: new Date(),
          metadata: {
            payment_result: {
              status: "success" as const,
              transaction_id: result.transaction_id,
              receipt_url: result.receipt_url,
              product_name: result.product_name,
              amount: result.amount,
            },
          },
        };
        addMessage(successMessage);
      } else {
        // 決済失敗
        sendMessage(`決済に失敗しました: ${result.error}`);
      }
    } catch (error: any) {
      console.error("WebAuthn attestation submission error:", error);
      clearWebauthnRequest();
      sendMessage(`デバイス認証処理中にエラーが発生しました: ${error.message}`);
    }
  };

  // WebAuthn認証失敗時の処理
  const handleWebAuthnError = (error: string) => {
    console.error("WebAuthn authentication failed:", error);
    clearWebauthnRequest();
    sendMessage(`デバイス認証に失敗しました: ${error}`);
  };

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* ヘッダー */}
      <header className="border-b bg-card p-4">
        <div className="container max-w-4xl mx-auto flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Avatar>
              <AvatarFallback className="bg-green-500">
                <Bot className="w-6 h-6 text-white" />
              </AvatarFallback>
            </Avatar>
            <div>
              <h1 className="text-xl font-semibold">AP2 Shopping Agent</h1>
              <p className="text-sm text-muted-foreground">
                商品の検索・購入をお手伝いします
              </p>
            </div>
          </div>

          {/* ユーザープロフィール & ログアウト（AP2準拠: JWT認証済みユーザー情報） */}
          {currentUser && (
            <div className="flex items-center gap-3">
              <div className="text-right hidden sm:block">
                <p className="text-sm font-medium">{currentUser.username}</p>
                <p className="text-xs text-muted-foreground">{currentUser.email}</p>
              </div>
              <Avatar className="w-9 h-9">
                <AvatarFallback className="bg-purple-500">
                  <User className="w-5 h-5 text-white" />
                </AvatarFallback>
              </Avatar>
              <button
                onClick={handleLogout}
                className="p-2 hover:bg-accent rounded-lg transition-colors"
                title="ログアウト"
              >
                <LogOut className="w-5 h-5 text-muted-foreground" />
              </button>
            </div>
          )}
        </div>
      </header>

      {/* チャットエリア */}
      <div className="flex-1 container max-w-4xl mx-auto p-4 overflow-hidden">
        <Card className="h-full flex flex-col">
          <CardContent className="flex-1 overflow-hidden p-0">
            <ScrollArea className="h-full p-6" ref={scrollAreaRef}>
              {messages.length === 0 && !isStreaming && (
                <div className="flex flex-col items-center justify-center h-full text-center text-muted-foreground">
                  <Bot className="w-16 h-16 mb-4 opacity-50" />
                  <p className="text-lg font-medium mb-2">
                    こんにちは！AP2 Shopping Agentです
                  </p>
                  <p className="text-sm">
                    何をお探しですか？例えば「かわいいグッズがほしい」のように教えてください。
                  </p>
                </div>
              )}

              {messages.map((message) => (
                <ChatMessage
                  key={message.id}
                  message={message}
                  onAddToCart={handleAddToCart}
                  onSelectCart={handleSelectCart}
                  onViewCartDetails={handleViewCartDetails}
                />
              ))}

              {/* ストリーミング中のLLM思考過程 */}
              {isStreaming && currentAgentThinking && (
                <div className="flex gap-3 mb-4">
                  <Avatar className="w-8 h-8 flex-shrink-0">
                    <AvatarFallback className="bg-green-500">
                      <Bot className="w-4 h-4 text-white" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="flex flex-col max-w-full">
                    <div className="rounded-lg px-4 py-2 text-sm bg-muted text-foreground opacity-60">
                      <p className="whitespace-pre-wrap font-mono text-xs">{currentAgentThinking}</p>
                      <span className="inline-block w-2 h-4 ml-1 bg-foreground animate-pulse" />
                    </div>
                  </div>
                </div>
              )}

              {/* ストリーミング中のエージェントメッセージ */}
              {isStreaming && currentAgentMessage && !currentAgentThinking && (
                <div className="flex gap-3 mb-4">
                  <Avatar className="w-8 h-8 flex-shrink-0">
                    <AvatarFallback className="bg-green-500">
                      <Bot className="w-4 h-4 text-white" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="flex flex-col max-w-full">
                    <div className="rounded-lg px-4 py-2 text-sm bg-muted text-foreground">
                      <p className="whitespace-pre-wrap">{currentAgentMessage}</p>
                      <span className="inline-block w-2 h-4 ml-1 bg-foreground animate-pulse" />
                    </div>
                  </div>
                </div>
              )}

              {/* 考え中UI：isStreamingがtrueだが、まだ何も応答がない場合 */}
              {isStreaming && !currentAgentThinking && !currentAgentMessage && (
                <div className="flex gap-3 mb-4">
                  <Avatar className="w-8 h-8 flex-shrink-0">
                    <AvatarFallback className="bg-green-500">
                      <Bot className="w-4 h-4 text-white" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="flex flex-col max-w-full">
                    <div className="rounded-lg px-4 py-3 text-sm bg-muted text-foreground">
                      <div className="flex items-center gap-2">
                        <div className="flex gap-1">
                          <span className="inline-block w-2 h-2 bg-foreground rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                          <span className="inline-block w-2 h-2 bg-foreground rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                          <span className="inline-block w-2 h-2 bg-foreground rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                        </div>
                        <span className="text-muted-foreground">考え中...</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* 商品カルーセル（isStreamingの外） */}
              {currentProducts.length > 0 && (
                <div className="mb-4">
                  <div className="flex gap-3">
                    <Avatar className="w-8 h-8 flex-shrink-0">
                      <AvatarFallback className="bg-green-500">
                        <Bot className="w-4 h-4 text-white" />
                      </AvatarFallback>
                    </Avatar>
                    <div className="w-full max-w-[600px]">
                      <ProductCarousel
                        products={currentProducts}
                        onAddToCart={handleAddToCart}
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* カート候補カルーセル（ストリーミング中のみ表示・確定後はChatMessage内で表示） */}
              {isStreaming && currentCartCandidates.length > 0 && (
                <div className="mb-4">
                  <div className="flex gap-3">
                    <Avatar className="w-8 h-8 flex-shrink-0">
                      <AvatarFallback className="bg-green-500">
                        <Bot className="w-4 h-4 text-white" />
                      </AvatarFallback>
                    </Avatar>
                    <div className="w-full max-w-[680px]">
                      <CartCarousel
                        cartCandidates={currentCartCandidates}
                        onSelectCart={handleSelectCart}
                        onViewDetails={handleViewCartDetails}
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Credential Provider選択はA2UI surfacesで描画（旧式UIは削除済み） */}

              {/* A2UI v0.9: サーフェスベースのUI描画 */}
              {Array.from(a2uiSurfaces.values()).map((surface) => (
                <div key={surface.surfaceId} className="mb-4">
                  <div className="flex gap-3">
                    <Avatar className="w-8 h-8 flex-shrink-0">
                      <AvatarFallback className="bg-green-500">
                        <Bot className="w-4 h-4 text-white" />
                      </AvatarFallback>
                    </Avatar>
                    <div className="w-full max-w-[600px]">
                      <A2UISurfaceRenderer
                        surfaceId={surface.surfaceId}
                        components={surface.components}
                        dataModel={surface.dataModel}
                        onDataModelChange={handleDataModelChange(surface.surfaceId)}
                        onAction={handleA2UIAction}
                      />
                    </div>
                  </div>
                </div>
              ))}


              {/* 支払い方法選択はA2UI surfacesで描画（旧式UIは削除済み） */}

              {/* AP2完全準拠: 決済完了時の領収書表示 */}
              {paymentCompletedInfo && paymentCompletedInfo.receipt_url && (
                <div className="space-y-2">
                  <Card className="border-green-200 bg-green-50">
                    <CardContent className="p-4">
                      <div className="flex items-start gap-3">
                        <div className="shrink-0 text-green-600 text-2xl">
                          ✅
                        </div>
                        <div className="flex-1 space-y-3">
                          <h3 className="font-semibold text-green-800">
                            決済が完了しました！
                          </h3>
                          <div className="text-sm space-y-2 text-gray-700">
                            <p><span className="font-medium">取引ID:</span> {paymentCompletedInfo.transaction_id}</p>
                            <p><span className="font-medium">商品:</span> {paymentCompletedInfo.product_name}</p>
                            <p><span className="font-medium">金額:</span> {paymentCompletedInfo.currency} {paymentCompletedInfo.amount?.toLocaleString()}</p>
                            <p><span className="font-medium">加盟店:</span> {paymentCompletedInfo.merchant_name}</p>
                          </div>
                          <div className="pt-2">
                            <button
                              onClick={async () => {
                                try {
                                  // AP2完全準拠：JWT認証付きで領収書をダウンロード
                                  const downloadUrl = paymentCompletedInfo.receipt_url.replace("http://payment_processor:8004", "http://localhost:8004");

                                  // JWTトークンを取得（AP2仕様準拠）
                                  const jwt = getAccessToken();

                                  if (!jwt) {
                                    alert("認証情報が見つかりません。再度ログインしてください。");
                                    return;
                                  }

                                  // fetchでJWT付きリクエスト（AP2完全準拠：セキュリティ）
                                  const response = await fetch(downloadUrl, {
                                    method: "GET",
                                    headers: {
                                      "Authorization": `Bearer ${jwt}`,
                                    },
                                  });

                                  if (!response.ok) {
                                    if (response.status === 401) {
                                      alert("認証に失敗しました。再度ログインしてください。");
                                    } else if (response.status === 403) {
                                      alert("この領収書にアクセスする権限がありません。");
                                    } else {
                                      alert("領収書のダウンロードに失敗しました。");
                                    }
                                    return;
                                  }

                                  // BlobとしてPDFを取得
                                  const blob = await response.blob();

                                  // Blob URLを作成して新しいタブで開く
                                  const blobUrl = URL.createObjectURL(blob);
                                  window.open(blobUrl, "_blank");

                                  // メモリリーク防止のため、5秒後にBlob URLを解放
                                  setTimeout(() => URL.revokeObjectURL(blobUrl), 5000);
                                } catch (error) {
                                  console.error("[Download Receipt] Error:", error);
                                  alert("領収書のダウンロード中にエラーが発生しました。");
                                }
                              }}
                              className="inline-flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors text-sm font-medium"
                            >
                              📄 領収書を表示
                            </button>
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              )}
            </ScrollArea>
          </CardContent>

          {/* 入力エリア */}
          <div className="p-4 border-t">
            {isPasskeyRegistered ? (
              <ChatInput
                onSendMessage={sendMessage}
                isStreaming={isStreaming}
                onStopStreaming={stopStreaming}
              />
            ) : (
              <div className="text-center text-sm text-muted-foreground py-4">
                Passkeyを登録してからチャットを開始してください
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* Passkey登録モーダル */}
      <PasskeyRegistration
        open={showPasskeyRegistration}
        onRegistered={handlePasskeyRegistered}
        onCancel={() => {}}
      />

      {/* 署名リクエストモーダル */}
      {signatureRequest && (
        <SignaturePromptModal
          signatureRequest={signatureRequest}
          onSign={handleSign}
          onCancel={clearSignatureRequest}
        />
      )}

      {/* WebAuthn認証モーダル */}
      {webauthnRequest && (
        <PasskeyAuthentication
          open={!!webauthnRequest}
          challenge={webauthnRequest.challenge}
          rpId={webauthnRequest.rp_id}
          timeout={webauthnRequest.timeout}
          onAuthenticated={handleWebAuthnAuthenticated}
          onError={handleWebAuthnError}
        />
      )}

      {/* カート詳細モーダル */}
      <CartDetailsModal
        open={!!selectedCartForDetails}
        cartCandidate={selectedCartForDetails}
        onClose={() => setSelectedCartForDetails(null)}
        onSelectCart={handleSelectCart}
      />

      {/* AP2完全準拠: Credential Provider用Passkeyは専用画面(/auth/register-passkey)で登録 */}
    </div>
  );
}
