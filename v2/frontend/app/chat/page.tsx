"use client";

import { useEffect, useRef, useState } from "react";
import { useSSEChat } from "@/hooks/useSSEChat";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { ChatInput } from "@/components/chat/ChatInput";
import { SignaturePromptModal } from "@/components/chat/SignaturePromptModal";
import { ShippingAddressForm } from "@/components/shipping/ShippingAddressForm";
import { PasskeyRegistration } from "@/components/auth/PasskeyRegistration";
import { PasskeyAuthentication } from "@/components/auth/PasskeyAuthentication";
import { ProductCarousel } from "@/components/product/ProductCarousel";
import { CartCarousel } from "@/components/cart/CartCarousel";
import { CartDetailsModal } from "@/components/cart/CartDetailsModal";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent } from "@/components/ui/card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Bot } from "lucide-react";
import { Product } from "@/lib/types/chat";

export default function ChatPage() {
  const {
    messages,
    isStreaming,
    currentAgentMessage,
    currentAgentThinking,  // LLMの思考内容
    currentProducts,
    currentCartCandidates,
    signatureRequest,
    credentialProviders,
    shippingFormRequest,
    paymentMethods,
    webauthnRequest,
    sessionId,
    sendMessage,
    addMessage,
    clearSignatureRequest,
    clearWebauthnRequest,
    stopStreaming,
    setSessionId,  // AP2 Step-up対応：セッションID設定関数
  } = useSSEChat();

  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const [isPasskeyRegistered, setIsPasskeyRegistered] = useState(false);
  const [showPasskeyRegistration, setShowPasskeyRegistration] = useState(false);
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [cart, setCart] = useState<Product[]>([]);
  const [selectedCartForDetails, setSelectedCartForDetails] = useState<any | null>(null);

  // Passkey登録状態をチェック
  useEffect(() => {
    const registered = localStorage.getItem("ap2_passkey_registered");
    const userId = localStorage.getItem("ap2_user_id");

    if (registered === "true" && userId) {
      setIsPasskeyRegistered(true);
      setCurrentUserId(userId);
    } else {
      setShowPasskeyRegistration(true);
    }
  }, []);

  // Step-up認証完了のコールバックをチェック
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const stepUpStatus = urlParams.get("step_up_status");
    const stepUpSessionId = urlParams.get("step_up_session_id");
    const sessionId = urlParams.get("session_id");

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
        console.log("[Step-up] Success - sending completion message to agent with session_id:", sessionId);
        setTimeout(() => {
          sendMessage(`step-up-completed:${stepUpSessionId}`);
        }, 500);
      } else if (stepUpStatus === "cancelled") {
        // キャンセル - ユーザーに通知
        console.log("[Step-up] Cancelled");
        setTimeout(() => {
          sendMessage("認証をキャンセルしました。別の支払い方法を選択してください。");
        }, 500);
      }
    }
  }, [sendMessage, setSessionId]);

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
    // カートIDをエージェントに送信
    sendMessage(cartCandidate.cart_mandate.id);
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

        const response = await fetch(`${shoppingAgentUrl}/cart/submit-signature`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
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
        // 従来の署名フロー（IntentMandate等）
        // Credential Providerに署名を送信
        const credentialProviderUrl = process.env.NEXT_PUBLIC_CREDENTIAL_PROVIDER_URL || "http://localhost:8003";
        const verifyResponse = await fetch(`${credentialProviderUrl}/verify/attestation`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            payment_mandate: signatureRequest.mandate,
            attestation: attestation,
          }),
        });

        const verifyResult = await verifyResponse.json();
        console.log("Verification result:", verifyResult);

        clearSignatureRequest();

        if (verifyResult.verified) {
          // 署名完了を自動的にエージェントに通知
          sendMessage("署名完了");
        } else {
          sendMessage("署名の検証に失敗しました。もう一度お試しください。");
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

      const response = await fetch(`${shoppingAgentUrl}/payment/submit-attestation`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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
        <div className="container max-w-4xl mx-auto flex items-center gap-3">
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
                    何をお探しですか？例えば「むぎぼーのグッズが欲しい」のように教えてください。
                  </p>
                </div>
              )}

              {messages.map((message) => (
                <ChatMessage
                  key={message.id}
                  message={message}
                  onAddToCart={handleAddToCart}
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

              {/* カート候補カルーセル（isStreamingの外・AP2/A2A仕様準拠） */}
              {currentCartCandidates.length > 0 && (
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

              {/* Credential Provider選択（isStreamingの外） */}
              {credentialProviders.length > 0 && (
                <div className="mb-4">
                  <div className="flex gap-3">
                    <Avatar className="w-8 h-8 flex-shrink-0">
                      <AvatarFallback className="bg-green-500">
                        <Bot className="w-4 h-4 text-white" />
                      </AvatarFallback>
                    </Avatar>
                    <div className="w-full max-w-[600px] space-y-2">
                      {credentialProviders.map((provider: any, index: number) => (
                        <Card
                          key={provider.id}
                          className="cursor-pointer hover:bg-accent transition-colors"
                          onClick={() => sendMessage(String(index + 1))}
                        >
                          <CardContent className="p-4">
                            <div className="flex items-center gap-3">
                              <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center text-xl font-bold">
                                {index + 1}
                              </div>
                              <div className="flex-1">
                                <h3 className="font-semibold">{provider.name}</h3>
                                <p className="text-sm text-muted-foreground">{provider.description}</p>
                                <p className="text-xs text-muted-foreground mt-1">
                                  対応: {provider.supported_methods.join(", ")}
                                </p>
                              </div>
                            </div>
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* 配送先フォーム（isStreamingの外） */}
              {shippingFormRequest && (
                <ShippingAddressForm
                  fields={shippingFormRequest.fields}
                  onSubmit={(shippingData) => {
                    // フォーム入力値をJSON文字列に変換してShopping Agentに送信
                    sendMessage(JSON.stringify(shippingData));
                  }}
                />
              )}

              {/* 支払い方法選択（isStreamingの外） */}
              {paymentMethods.length > 0 && (
                <div className="mb-4">
                  <div className="flex gap-3">
                    <Avatar className="w-8 h-8 flex-shrink-0">
                      <AvatarFallback className="bg-green-500">
                        <Bot className="w-4 h-4 text-white" />
                      </AvatarFallback>
                    </Avatar>
                    <div className="w-full max-w-[600px] space-y-2">
                      {paymentMethods.map((method: any, index: number) => (
                        <Card
                          key={method.id}
                          className="cursor-pointer hover:bg-accent transition-colors"
                          onClick={() => sendMessage(String(index + 1))}
                        >
                          <CardContent className="p-4">
                            <div className="flex items-center gap-3">
                              <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center text-xl font-bold">
                                {index + 1}
                              </div>
                              <div className="flex-1">
                                <h3 className="font-semibold">
                                  {method.brand?.toUpperCase()} **** {method.last4}
                                </h3>
                                <p className="text-sm text-muted-foreground">
                                  {method.type === "card" ? "クレジットカード" : method.type}
                                </p>
                              </div>
                            </div>
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  </div>
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
    </div>
  );
}
