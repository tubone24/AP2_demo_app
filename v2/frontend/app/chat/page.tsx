"use client";

import { useEffect, useRef, useState } from "react";
import { useSSEChat } from "@/hooks/useSSEChat";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { ChatInput } from "@/components/chat/ChatInput";
import { SignaturePromptModal } from "@/components/chat/SignaturePromptModal";
import { PasskeyRegistration } from "@/components/auth/PasskeyRegistration";
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
    sendMessage,
    clearSignatureRequest,
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
                    何をお探しですか？例えば「ランニングシューズが欲しい」のように教えてください。
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
    </div>
  );
}
