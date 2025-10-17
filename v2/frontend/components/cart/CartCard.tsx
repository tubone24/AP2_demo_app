"use client";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ShoppingCart, Info } from "lucide-react";

interface CartItem {
  id: string;
  name: string;
  description?: string;
  quantity: number;
  unit_price: {
    value: string;
    currency: string;
  };
  total_price: {
    value: string;
    currency: string;
  };
  image_url?: string;
}

interface CartMandate {
  id: string;
  items: CartItem[];
  subtotal: {
    value: string;
    currency: string;
  };
  tax: {
    value: string;
    currency: string;
  };
  shipping: {
    cost: {
      value: string;
      currency: string;
    };
  };
  total: {
    value: string;
    currency: string;
  };
  cart_metadata?: {
    name: string;
    description: string;
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
  const { items, total, cart_metadata } = cart_mandate;

  const cartName = cart_metadata?.name || artifact_name || "カート";
  const cartDescription = cart_metadata?.description || "";

  // 最初の3つの商品を表示
  const displayItems = items.slice(0, 3);
  const hasMoreItems = items.length > 3;

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
            {items.length}点
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="flex-1 flex flex-col">
        {/* 商品リスト（最大3つ） */}
        <div className="space-y-2 mb-4 flex-1">
          {displayItems.map((item, index) => (
            <div
              key={item.id}
              className="flex items-center gap-2 p-2 bg-muted/30 rounded-md"
            >
              {item.image_url && (
                <img
                  src={item.image_url}
                  alt={item.name}
                  className="w-10 h-10 object-cover rounded"
                />
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{item.name}</p>
                <p className="text-xs text-muted-foreground">
                  ¥{parseFloat(item.unit_price.value).toLocaleString()} × {item.quantity}
                </p>
              </div>
              <p className="text-sm font-medium">
                ¥{parseFloat(item.total_price.value).toLocaleString()}
              </p>
            </div>
          ))}

          {hasMoreItems && (
            <p className="text-xs text-muted-foreground text-center py-1">
              他{items.length - 3}点...
            </p>
          )}
        </div>

        {/* 合計金額 */}
        <div className="border-t pt-3 mb-3">
          <div className="flex justify-between items-center">
            <span className="text-sm font-medium">合計</span>
            <span className="text-lg font-bold text-primary">
              ¥{parseFloat(total.value).toLocaleString()}
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
