"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ShoppingCart, Package, Truck, MapPin } from "lucide-react";

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
  sku?: string;
  category?: string;
  brand?: string;
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
    address?: any;
    method?: string;
    cost: {
      value: string;
      currency: string;
    };
    estimated_delivery?: string;
  };
  total: {
    value: string;
    currency: string;
  };
  cart_metadata?: {
    name: string;
    description: string;
  };
  merchant_name?: string;
}

interface CartCandidate {
  artifact_id: string;
  artifact_name: string;
  cart_mandate: CartMandate;
}

interface CartDetailsModalProps {
  open: boolean;
  cartCandidate: CartCandidate | null;
  onClose: () => void;
  onSelectCart?: (cartCandidate: CartCandidate) => void;
}

export function CartDetailsModal({
  open,
  cartCandidate,
  onClose,
  onSelectCart,
}: CartDetailsModalProps) {
  if (!cartCandidate) {
    return null;
  }

  const { cart_mandate, artifact_name } = cartCandidate;
  const { items, subtotal, tax, shipping, total, cart_metadata, merchant_name } = cart_mandate;

  const cartName = cart_metadata?.name || artifact_name || "カート";
  const cartDescription = cart_metadata?.description || "";

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[90vh]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Package className="w-5 h-5" />
            {cartName}
          </DialogTitle>
          {cartDescription && (
            <DialogDescription>{cartDescription}</DialogDescription>
          )}
        </DialogHeader>

        <ScrollArea className="max-h-[60vh] pr-4">
          <div className="space-y-4">
            {/* 商品リスト */}
            <div>
              <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                <ShoppingCart className="w-4 h-4" />
                商品一覧（{items.length}点）
              </h3>
              <div className="space-y-3">
                {items.map((item) => (
                  <div
                    key={item.id}
                    className="flex gap-3 p-3 bg-muted/30 rounded-lg"
                  >
                    {item.image_url && (
                      <img
                        src={item.image_url}
                        alt={item.name}
                        className="w-20 h-20 object-cover rounded"
                      />
                    )}
                    <div className="flex-1 min-w-0">
                      <h4 className="font-medium">{item.name}</h4>
                      {item.description && (
                        <p className="text-sm text-muted-foreground mt-1">
                          {item.description}
                        </p>
                      )}
                      <div className="flex gap-2 mt-2">
                        {item.brand && (
                          <Badge variant="outline" className="text-xs">
                            {item.brand}
                          </Badge>
                        )}
                        {item.category && (
                          <Badge variant="secondary" className="text-xs">
                            {item.category}
                          </Badge>
                        )}
                      </div>
                      {item.sku && (
                        <p className="text-xs text-muted-foreground mt-1">
                          SKU: {item.sku}
                        </p>
                      )}
                    </div>
                    <div className="text-right">
                      <p className="text-sm text-muted-foreground">
                        ¥{parseFloat(item.unit_price.value).toLocaleString()} × {item.quantity}
                      </p>
                      <p className="text-lg font-semibold mt-1">
                        ¥{parseFloat(item.total_price.value).toLocaleString()}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <Separator />

            {/* 配送情報 */}
            {shipping && (
              <div>
                <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                  <Truck className="w-4 h-4" />
                  配送情報
                </h3>
                <div className="space-y-2 text-sm">
                  {shipping.method && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">配送方法</span>
                      <span className="font-medium">{shipping.method}</span>
                    </div>
                  )}
                  {shipping.estimated_delivery && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">お届け予定</span>
                      <span className="font-medium">
                        {new Date(shipping.estimated_delivery).toLocaleDateString('ja-JP')}
                      </span>
                    </div>
                  )}
                  {shipping.address && (
                    <div className="mt-2 p-2 bg-muted/30 rounded">
                      <div className="flex items-start gap-2">
                        <MapPin className="w-4 h-4 mt-0.5 text-muted-foreground" />
                        <div className="text-xs">
                          <p className="font-medium">{shipping.address.recipient || "配送先"}</p>
                          <p className="text-muted-foreground mt-1">
                            〒{shipping.address.postal_code || ""}
                            <br />
                            {shipping.address.state || ""} {shipping.address.city || ""}
                            <br />
                            {shipping.address.address_line1 || ""}
                            {shipping.address.address_line2 && (
                              <>
                                <br />
                                {shipping.address.address_line2}
                              </>
                            )}
                          </p>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            <Separator />

            {/* 金額詳細 */}
            <div>
              <h3 className="text-sm font-semibold mb-3">金額詳細</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">小計</span>
                  <span>¥{parseFloat(subtotal.value).toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">税金</span>
                  <span>¥{parseFloat(tax.value).toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">送料</span>
                  <span>¥{parseFloat(shipping.cost.value).toLocaleString()}</span>
                </div>
                <Separator />
                <div className="flex justify-between text-lg font-bold pt-2">
                  <span>合計</span>
                  <span className="text-primary">
                    ¥{parseFloat(total.value).toLocaleString()}
                  </span>
                </div>
              </div>
            </div>

            {/* 販売店情報 */}
            {merchant_name && (
              <>
                <Separator />
                <div className="text-xs text-muted-foreground">
                  販売元: {merchant_name}
                </div>
              </>
            )}
          </div>
        </ScrollArea>

        {/* アクションボタン */}
        <div className="flex gap-2 pt-4 border-t">
          <Button variant="outline" onClick={onClose} className="flex-1">
            閉じる
          </Button>
          <Button
            onClick={() => {
              onSelectCart?.(cartCandidate);
              onClose();
            }}
            className="flex-1"
          >
            <ShoppingCart className="w-4 h-4 mr-2" />
            このカートを選択
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
