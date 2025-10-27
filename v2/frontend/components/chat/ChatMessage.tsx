"use client";

import { ChatMessage as ChatMessageType } from "@/lib/types/chat";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { ProductCarousel } from "@/components/product/ProductCarousel";
import { cn } from "@/lib/utils";
import { Bot, User } from "lucide-react";

interface ChatMessageProps {
  message: ChatMessageType;
  onAddToCart?: (product: any) => void;
}

export function ChatMessage({ message, onAddToCart }: ChatMessageProps) {
  const isUser = message.role === "user";
  const hasProducts = message.metadata?.products && message.metadata.products.length > 0;

  // AP2完全準拠: 領収書ボタンは緑のカード（page.tsx）に統合されるため、
  // ChatMessageでは表示しない。メッセージテキストのみ表示。
  let displayContent = message.content;

  // 従来の正規表現でURLを検出して削除（表示しない）
  const receiptUrlPattern = /http:\/\/payment_processor:8004\/receipts\/([a-zA-Z0-9_]+)\.pdf/;
  const receiptMatch = message.content.match(receiptUrlPattern);

  if (receiptMatch) {
    // URLをテキストから削除（改行も削除）
    displayContent = displayContent.replace(receiptMatch[0], "").replace(/\n\n+/g, "\n\n").trim();
  }


  return (
    <div
      className={cn(
        "flex gap-3 mb-4",
        isUser ? "flex-row-reverse" : "flex-row"
      )}
    >
      <Avatar className="w-8 h-8 flex-shrink-0">
        <AvatarFallback className={cn(isUser ? "bg-blue-500" : "bg-green-500")}>
          {isUser ? <User className="w-4 h-4 text-white" /> : <Bot className="w-4 h-4 text-white" />}
        </AvatarFallback>
      </Avatar>

      <div
        className={cn(
          "flex flex-col",
          isUser ? "items-end max-w-[80%]" : "items-start max-w-full"
        )}
      >
        <div
          className={cn(
            "rounded-lg px-4 py-2 text-sm",
            isUser
              ? "bg-blue-500 text-white"
              : "bg-muted text-foreground"
          )}
        >
          <p className="whitespace-pre-wrap">{displayContent}</p>
        </div>

        {/* 商品カルーセル */}
        {hasProducts && (
          <div className="mt-3 w-full max-w-[600px]">
            <ProductCarousel
              products={message.metadata!.products!}
              onAddToCart={onAddToCart}
            />
          </div>
        )}

        <span className="text-xs text-muted-foreground mt-1">
          {message.timestamp.toLocaleTimeString("ja-JP", {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>
    </div>
  );
}
