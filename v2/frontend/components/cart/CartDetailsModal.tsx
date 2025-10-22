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

interface PaymentShippingOption {
  id: string;
  label: string;
  amount: PaymentCurrencyAmount;
  selected?: boolean;
}

interface PaymentRequest {
  method_data: any[];
  details: {
    id: string;
    display_items: PaymentItem[];
    total: PaymentItem;
    shipping_options?: PaymentShippingOption[];
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

  // AP2準拠の構造から情報を取得
  const { contents, _metadata } = cart_mandate;
  const { payment_request, merchant_name } = contents;
  const { display_items, total, shipping_options } = payment_request.details;
  const { shipping_address } = payment_request;

  const cartName = _metadata?.cart_name || artifact_name || "カート";
  const cartDescription = _metadata?.cart_description || "";

  // display_itemsを分類
  const productItems = display_items.filter(item => item.refund_period && item.refund_period > 0);
  const shippingItem = display_items.find(item => item.label.includes("送料"));
  const taxItem = display_items.find(item => item.label.includes("税"));

  // 小計を計算（商品の合計）
  const subtotal = productItems.reduce((sum, item) => sum + item.amount.value, 0);

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
                商品一覧（{productItems.length}点）
              </h3>
              <div className="space-y-3">
                {productItems.map((item, index) => {
                  // _metadata.raw_itemsから詳細情報を取得
                  const rawItem = _metadata?.raw_items?.[index];

                  return (
                    <div
                      key={index}
                      className="flex gap-3 p-3 bg-muted/30 rounded-lg"
                    >
                      {rawItem?.image_url && (
                        <img
                          src={rawItem.image_url}
                          alt={item.label}
                          className="w-20 h-20 object-cover rounded"
                        />
                      )}
                      <div className="flex-1 min-w-0">
                        <h4 className="font-medium">{item.label}</h4>
                        {rawItem?.description && (
                          <p className="text-sm text-muted-foreground mt-1">
                            {rawItem.description}
                          </p>
                        )}
                        <div className="flex gap-2 mt-2">
                          {rawItem?.brand && (
                            <Badge variant="outline" className="text-xs">
                              {rawItem.brand}
                            </Badge>
                          )}
                          {rawItem?.category && (
                            <Badge variant="secondary" className="text-xs">
                              {rawItem.category}
                            </Badge>
                          )}
                        </div>
                        {rawItem?.sku && (
                          <p className="text-xs text-muted-foreground mt-1">
                            SKU: {rawItem.sku}
                          </p>
                        )}
                      </div>
                      <div className="text-right">
                        {rawItem && (
                          <p className="text-sm text-muted-foreground">
                            ¥{parseFloat(rawItem.unit_price.value).toLocaleString()} × {rawItem.quantity}
                          </p>
                        )}
                        <p className="text-lg font-semibold mt-1">
                          ¥{item.amount.value.toLocaleString()}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <Separator />

            {/* 配送情報 */}
            {(shipping_options || shipping_address) && (
              <div>
                <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                  <Truck className="w-4 h-4" />
                  配送情報
                </h3>
                <div className="space-y-2 text-sm">
                  {shipping_options && shipping_options.length > 0 && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">配送方法</span>
                      <span className="font-medium">
                        {shipping_options.find(opt => opt.selected)?.label || shipping_options[0].label}
                      </span>
                    </div>
                  )}
                  {shipping_address && (
                    <div className="mt-2 p-2 bg-muted/30 rounded">
                      <div className="flex items-start gap-2">
                        <MapPin className="w-4 h-4 mt-0.5 text-muted-foreground" />
                        <div className="text-xs">
                          <p className="font-medium">{shipping_address.recipient || "配送先"}</p>
                          <p className="text-muted-foreground mt-1">
                            {shipping_address.postal_code && `〒${shipping_address.postal_code}`}
                            <br />
                            {shipping_address.region || ""} {shipping_address.city || ""}
                            <br />
                            {shipping_address.address_line && shipping_address.address_line.join(' ')}
                          </p>
                          {shipping_address.phone_number && (
                            <p className="text-muted-foreground mt-1">
                              TEL: {shipping_address.phone_number}
                            </p>
                          )}
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
                  <span>¥{subtotal.toLocaleString()}</span>
                </div>
                {taxItem && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{taxItem.label}</span>
                    <span>¥{taxItem.amount.value.toLocaleString()}</span>
                  </div>
                )}
                {shippingItem && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{shippingItem.label}</span>
                    <span>¥{shippingItem.amount.value.toLocaleString()}</span>
                  </div>
                )}
                <Separator />
                <div className="flex justify-between text-lg font-bold pt-2">
                  <span>合計</span>
                  <span className="text-primary">
                    ¥{total.amount.value.toLocaleString()}
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
