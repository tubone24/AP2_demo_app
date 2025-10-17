"use client";

import { useEffect, useRef, useState } from "react";
import { useSSEChat } from "@/hooks/useSSEChat";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { ChatInput } from "@/components/chat/ChatInput";
import { SignaturePromptModal } from "@/components/chat/SignaturePromptModal";
import { PasskeyRegistration } from "@/components/auth/PasskeyRegistration";
import { PasskeyAuthentication } from "@/components/auth/PasskeyAuthentication";
import { ProductCarousel } from "@/components/product/ProductCarousel";
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
    currentProducts,
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
  } = useSSEChat();

  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const [isPasskeyRegistered, setIsPasskeyRegistered] = useState(false);
  const [showPasskeyRegistration, setShowPasskeyRegistration] = useState(false);
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [cart, setCart] = useState<Product[]>([]);

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

  // 署名処理
  const handleSign = async (attestation: any) => {
    console.log("Signature completed:", attestation);

    try {
      if (!signatureRequest) return;

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

              {/* ストリーミング中のエージェントメッセージ */}
              {isStreaming && currentAgentMessage && (
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

                    {/* ストリーミング中の商品カルーセル */}
                    {currentProducts.length > 0 && (
                      <div className="mt-3 w-full max-w-[600px]">
                        <ProductCarousel
                          products={currentProducts}
                          onAddToCart={handleAddToCart}
                        />
                      </div>
                    )}
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
                <div className="mb-4">
                  <div className="flex gap-3">
                    <Avatar className="w-8 h-8 flex-shrink-0">
                      <AvatarFallback className="bg-green-500">
                        <Bot className="w-4 h-4 text-white" />
                      </AvatarFallback>
                    </Avatar>
                    <div className="w-full max-w-[600px]">
                      <Card>
                        <CardContent className="p-4 space-y-3">
                          {shippingFormRequest.fields.map((field: any) => (
                            <div key={field.name}>
                              <label className="block text-sm font-medium mb-1">
                                {field.label}
                                {field.required && <span className="text-red-500 ml-1">*</span>}
                              </label>
                              {field.type === "select" ? (
                                <select
                                  className="w-full px-3 py-2 border rounded-md"
                                  defaultValue={field.default}
                                >
                                  {field.options.map((opt: any) => (
                                    <option key={opt.value} value={opt.value}>
                                      {opt.label}
                                    </option>
                                  ))}
                                </select>
                              ) : (
                                <input
                                  type={field.type}
                                  placeholder={field.placeholder}
                                  className="w-full px-3 py-2 border rounded-md"
                                  required={field.required}
                                />
                              )}
                            </div>
                          ))}
                          <button
                            onClick={() => {
                              // デモ用：固定値を送信
                              sendMessage("デモ配送先");
                            }}
                            className="w-full px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
                          >
                            配送先を確定
                          </button>
                        </CardContent>
                      </Card>
                    </div>
                  </div>
                </div>
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
    </div>
  );
}
