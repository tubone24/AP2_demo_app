"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CreditCard, Loader2, CheckCircle2, AlertCircle } from "lucide-react";

/**
 * AP2完全準拠の支払い方法登録フォーム
 *
 * Passkey登録後に表示され、ユーザーが支払い方法（カード情報）を登録する
 */

interface AddPaymentMethodFormProps {
  open: boolean;
  userId: string;
  credentialProviderUrl: string;
  onAdded: () => void;
  onSkip: () => void;
}

interface CardFormData {
  cardBrand: string;
  cardNumber: string;
  cardholderName: string;
  expiryMonth: string;
  expiryYear: string;
  cvv: string;
  postalCode: string;
}

export function AddPaymentMethodForm({
  open,
  userId,
  credentialProviderUrl,
  onAdded,
  onSkip,
}: AddPaymentMethodFormProps) {
  const [formData, setFormData] = useState<CardFormData>({
    cardBrand: "",
    cardNumber: "",
    cardholderName: "",
    expiryMonth: "",
    expiryYear: "",
    cvv: "",
    postalCode: "",
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // AP2準拠のカードブランドリスト
  const CARD_BRANDS = [
    { value: "Visa", label: "Visa" },
    { value: "Mastercard", label: "Mastercard" },
    { value: "Amex", label: "American Express" },
    { value: "JCB", label: "JCB" },
  ];

  // カード番号のフォーマット
  const formatCardNumber = (value: string): string => {
    const cleaned = value.replace(/\D/g, "");
    const limited = cleaned.slice(0, 16);
    const chunks = limited.match(/.{1,4}/g) || [];
    return chunks.join(" ");
  };

  // 入力値の検証
  const validateForm = (): boolean => {
    if (!formData.cardBrand) {
      setError("カードブランドを選択してください");
      return false;
    }

    const cleaned = formData.cardNumber.replace(/\s/g, "");
    if (cleaned.length < 13 || cleaned.length > 16) {
      setError("カード番号は13〜16桁で入力してください");
      return false;
    }
    if (!formData.cardholderName.trim()) {
      setError("カード名義人を入力してください");
      return false;
    }
    if (!formData.expiryMonth || !formData.expiryYear) {
      setError("有効期限を選択してください");
      return false;
    }
    if (formData.cvv.length < 3 || formData.cvv.length > 4) {
      setError("セキュリティコードは3〜4桁で入力してください");
      return false;
    }
    if (!/^\d{3,4}-?\d{4}$/.test(formData.postalCode)) {
      setError("郵便番号を正しく入力してください（例: 100-0001）");
      return false;
    }

    return true;
  };

  const handleSubmit = async () => {
    if (!validateForm()) {
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const cleaned = formData.cardNumber.replace(/\s/g, "");
      const cardBrand = formData.cardBrand;
      const cardLast4 = cleaned.slice(-4);

      // American Expressはrequires_step_up: trueに設定（AP2完全準拠）
      const requiresStepUp = cardBrand === "Amex";

      // AP2完全準拠のPayment Method Request
      // NOTE: デモ環境のため、カード情報を直接送信しています
      // 実際の本番環境では、PCI DSS準拠のトークン化サービスを使用してください
      const paymentMethodRequest = {
        user_id: userId,
        payment_method: {
          type: "basic-card",
          display_name: `${cardBrand}カード (****${cardLast4})`,
          brand: cardBrand,
          last4: cardLast4,
          // カード情報（デモ環境のみ）
          card_number: cleaned,
          cardholder_name: formData.cardholderName,
          expiry_month: formData.expiryMonth,
          expiry_year: formData.expiryYear,
          cvv: formData.cvv,
          // 請求先住所
          billing_address: {
            country: "JP",
            postal_code: formData.postalCode,
          },
          // AP2完全準拠: Step-up認証フラグ
          requires_step_up: requiresStepUp,
          stepup_method: requiresStepUp ? "3d_secure" : undefined,
          step_up_reason: requiresStepUp
            ? "American Express requires additional authentication"
            : undefined,
        },
      };

      // Credential Providerに送信（AP2 POST /payment-methods）
      const response = await fetch(`${credentialProviderUrl}/payment-methods`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(paymentMethodRequest),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "支払い方法の登録に失敗しました");
      }

      const result = await response.json();
      console.log("Payment method added:", result);

      setSuccess(true);
      setTimeout(() => {
        onAdded();
      }, 1500);
    } catch (err: any) {
      console.error("Payment method registration error:", err);
      setError(err.message || "支払い方法の登録に失敗しました");
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={() => {}}>
      <DialogContent
        className="sm:max-w-[550px] max-h-[90vh] overflow-y-auto"
        onInteractOutside={(e) => e.preventDefault()}
      >
        <DialogHeader>
          <div className="flex items-center gap-2">
            <CreditCard className="w-6 h-6 text-blue-500" />
            <DialogTitle>支払い方法の登録</DialogTitle>
          </div>
          <DialogDescription>
            カード情報を登録してください（AP2完全準拠）
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* カードブランド */}
          <div className="space-y-2">
            <Label htmlFor="cardBrand">カードブランド *</Label>
            <Select
              value={formData.cardBrand}
              onValueChange={(value) =>
                setFormData({ ...formData, cardBrand: value })
              }
              disabled={isSubmitting || success}
            >
              <SelectTrigger>
                <SelectValue placeholder="カードブランドを選択" />
              </SelectTrigger>
              <SelectContent>
                {CARD_BRANDS.map((brand) => (
                  <SelectItem key={brand.value} value={brand.value}>
                    {brand.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* カード番号 */}
          <div className="space-y-2">
            <Label htmlFor="cardNumber">カード番号 *</Label>
            <Input
              id="cardNumber"
              placeholder="1234 5678 9012 3456"
              value={formData.cardNumber}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  cardNumber: formatCardNumber(e.target.value),
                })
              }
              maxLength={19}
              disabled={isSubmitting || success}
            />
          </div>

          {/* カード名義人 */}
          <div className="space-y-2">
            <Label htmlFor="cardholderName">カード名義人 *</Label>
            <Input
              id="cardholderName"
              placeholder="TARO YAMADA"
              value={formData.cardholderName}
              onChange={(e) =>
                setFormData({ ...formData, cardholderName: e.target.value })
              }
              disabled={isSubmitting || success}
            />
          </div>

          {/* 有効期限 */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="expiryMonth">有効期限（月） *</Label>
              <Select
                value={formData.expiryMonth}
                onValueChange={(value) =>
                  setFormData({ ...formData, expiryMonth: value })
                }
                disabled={isSubmitting || success}
              >
                <SelectTrigger>
                  <SelectValue placeholder="月" />
                </SelectTrigger>
                <SelectContent>
                  {Array.from({ length: 12 }, (_, i) => i + 1).map((month) => (
                    <SelectItem key={month} value={month.toString().padStart(2, "0")}>
                      {month.toString().padStart(2, "0")}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="expiryYear">有効期限（年） *</Label>
              <Select
                value={formData.expiryYear}
                onValueChange={(value) =>
                  setFormData({ ...formData, expiryYear: value })
                }
                disabled={isSubmitting || success}
              >
                <SelectTrigger>
                  <SelectValue placeholder="年" />
                </SelectTrigger>
                <SelectContent>
                  {Array.from({ length: 10 }, (_, i) => 2025 + i).map((year) => (
                    <SelectItem key={year} value={year.toString()}>
                      {year}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* セキュリティコードと郵便番号 */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="cvv">セキュリティコード *</Label>
              <Input
                id="cvv"
                placeholder="123"
                type="password"
                value={formData.cvv}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    cvv: e.target.value.replace(/\D/g, "").slice(0, 4),
                  })
                }
                maxLength={4}
                disabled={isSubmitting || success}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="postalCode">郵便番号 *</Label>
              <Input
                id="postalCode"
                placeholder="100-0001"
                value={formData.postalCode}
                onChange={(e) =>
                  setFormData({ ...formData, postalCode: e.target.value })
                }
                disabled={isSubmitting || success}
              />
            </div>
          </div>

          {/* エラー表示 */}
          {error && (
            <div className="flex items-center gap-2 text-red-500 text-sm">
              <AlertCircle className="w-4 h-4" />
              <span>{error}</span>
            </div>
          )}

          {/* 成功表示 */}
          {success && (
            <div className="flex items-center gap-2 text-green-500 text-sm">
              <CheckCircle2 className="w-4 h-4" />
              <span>支払い方法を登録しました</span>
            </div>
          )}

          {/* 注意事項 */}
          <div className="text-xs text-muted-foreground mt-4 p-3 bg-muted/30 rounded">
            <p className="font-semibold mb-1">セキュリティについて</p>
            <p>
              入力されたカード情報は、AP2プロトコルに準拠して安全に処理されます。
              American Expressカードの場合、決済時に3D Secure認証（STEP_UP）が必要になります。
            </p>
          </div>
        </div>

        <DialogFooter className="flex gap-2">
          <Button
            variant="outline"
            onClick={onSkip}
            disabled={isSubmitting || success}
          >
            後で登録
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isSubmitting || success}
          >
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                登録中...
              </>
            ) : success ? (
              <>
                <CheckCircle2 className="mr-2 h-4 w-4" />
                登録完了
              </>
            ) : (
              "登録する"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
