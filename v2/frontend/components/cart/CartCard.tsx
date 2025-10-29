"use client";

import Image from "next/image";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ShoppingCart, Info } from "lucide-react";

// AP2準拠の型定義
// refs/AP2-main/src/ap2/types/payment_request.py

interface PaymentCurrencyAmount {
  currency: string;
  value: number;
}

interface PaymentItem {
  label: string;
  amount: PaymentCurrencyAmount;
  pending?: boolean;
  refund_period?: number;
}

interface ContactAddress {
  recipient?: string;
  postal_code?: string;
  city?: string;
  region?: string;
  country?: string;
  address_line?: string[];
  phone_number?: string;
}

interface PaymentRequest {
  method_data: any[];
  details: {
    id: string;
    display_items: PaymentItem[];
    total: PaymentItem;
    shipping_options?: any[];
    modifiers?: any[];
  };
  options?: any;
  shipping_address?: ContactAddress;
}

interface CartContents {
  id: string;
  user_cart_confirmation_required: boolean;
  payment_request: PaymentRequest;
  cart_expiry: string;
  merchant_name: string;
}

interface CartMandate {
  contents: CartContents;
  merchant_authorization?: string | null;
  _metadata?: {
    intent_mandate_id?: string;
    merchant_id?: string;
    created_at?: string;
    cart_name?: string;
    cart_description?: string;
    raw_items?: any[];
  };
}

interface CartCandidate {
  artifact_id: string;
  artifact_name: string;
  cart_mandate: CartMandate;
}

interface CartCardProps {
  cartCandidate: CartCandidate;
  onSelectCart?: (cartCandidate: CartCandidate) => void;
  onViewDetails?: (cartCandidate: CartCandidate) => void;
}

export function CartCard({
  cartCandidate,
  onSelectCart,
  onViewDetails,
}: CartCardProps) {
  const { cart_mandate, artifact_name } = cartCandidate;

  // AP2準拠の構造から情報を取得
  const { contents, _metadata } = cart_mandate;
  const { payment_request } = contents;
  const { display_items, total } = payment_request.details;

  const cartName = _metadata?.cart_name || artifact_name || "カート";
  const cartDescription = _metadata?.cart_description || "";

  // display_itemsから商品アイテムのみを抽出（送料・税金を除く）
  // 商品は通常refund_period > 0を持つ
  const productItems = display_items.filter(item =>
    item.refund_period && item.refund_period > 0
  );

  // 最初の3つの商品を表示
  const displayProductItems = productItems.slice(0, 3);
  const hasMoreItems = productItems.length > 3;

  return (
    <Card className="h-full flex flex-col hover:shadow-lg transition-shadow">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <CardTitle className="text-lg">{cartName}</CardTitle>
            {cartDescription && (
              <CardDescription className="text-sm mt-1">
                {cartDescription}
              </CardDescription>
            )}
          </div>
          <Badge variant="outline" className="ml-2">
            {productItems.length}点
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="flex-1 flex flex-col">
        {/* 商品リスト（最大3つ） */}
        <div className="space-y-2 mb-4 flex-1">
          {displayProductItems.map((item, index) => {
            // _metadata.raw_itemsから画像URLと数量を取得（あれば）
            const rawItem = _metadata?.raw_items?.[index];
            const imageUrl = rawItem?.image_url || rawItem?.metadata?.image_url || "https://placehold.co/100x100/EEE/999?text=No+Image";
            const isLocalPath = imageUrl.startsWith("/");

            return (
              <div
                key={index}
                className="flex items-center gap-2 p-2 bg-muted/30 rounded-md"
              >
                {rawItem?.image_url && (
                  <div className="relative w-10 h-10 flex-shrink-0">
                    <Image
                      src={imageUrl}
                      alt={item.label}
                      fill
                      className="object-cover rounded"
                      sizes="40px"
                      unoptimized={isLocalPath}
                    />
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{item.label}</p>
                  {rawItem && (
                    <p className="text-xs text-muted-foreground">
                      ¥{rawItem.unit_price.value.toLocaleString()} × {rawItem.quantity}
                    </p>
                  )}
                </div>
                <p className="text-sm font-medium">
                  ¥{item.amount.value.toLocaleString()}
                </p>
              </div>
            );
          })}

          {hasMoreItems && (
            <p className="text-xs text-muted-foreground text-center py-1">
              他{productItems.length - 3}点...
            </p>
          )}
        </div>

        {/* 合計金額 */}
        <div className="border-t pt-3 mb-3">
          <div className="flex justify-between items-center">
            <span className="text-sm font-medium">合計</span>
            <span className="text-lg font-bold text-primary">
              ¥{total.amount.value.toLocaleString()}
            </span>
          </div>
        </div>

        {/* アクションボタン */}
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            className="flex-1"
            onClick={() => onViewDetails?.(cartCandidate)}
          >
            <Info className="w-4 h-4 mr-1" />
            詳細
          </Button>
          <Button
            size="sm"
            className="flex-1"
            onClick={() => onSelectCart?.(cartCandidate)}
          >
            <ShoppingCart className="w-4 h-4 mr-1" />
            選択
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
