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
import { Separator } from "@/components/ui/separator";
import { SignatureRequestEvent, IntentMandate, CartMandate, PaymentMandate } from "@/lib/types/chat";
import { signWithPasskey } from "@/lib/webauthn";
import { ShieldCheck, AlertCircle, Loader2 } from "lucide-react";

interface SignaturePromptModalProps {
  signatureRequest: SignatureRequestEvent;
  onSign: (attestation: any) => void;
  onCancel: () => void;
}

export function SignaturePromptModal({
  signatureRequest,
  onSign,
  onCancel,
}: SignaturePromptModalProps) {
  const [isSigning, setIsSigning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { mandate, mandate_type } = signatureRequest;

  const handleSign = async () => {
    setIsSigning(true);
    setError(null);

    try {
      // チャレンジ生成（Base64URL形式）
      const challengeData = JSON.stringify({ mandate_id: mandate.id, timestamp: Date.now() });
      const challenge = btoa(challengeData)
        .replace(/\+/g, "-")
        .replace(/\//g, "_")
        .replace(/=/g, "");

      // Passkey署名
      const attestation = await signWithPasskey(
        challenge,
        process.env.NEXT_PUBLIC_RP_ID || "localhost"
      );

      // 署名完了
      onSign(attestation);
    } catch (err: any) {
      console.error("Signature error:", err);
      setError(err.message || "署名に失敗しました");
      setIsSigning(false);
    }
  };

  // Mandate内容の表示
  const renderMandateDetails = () => {
    switch (mandate_type) {
      case "intent":
        const intentMandate = mandate as IntentMandate;
        return (
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-sm text-muted-foreground">最大金額</span>
              <span className="text-sm font-medium">
                {intentMandate.max_amount?.currency} {parseFloat(intentMandate.max_amount?.value || "0").toLocaleString()}
              </span>
            </div>
            {intentMandate.allowed_merchants && intentMandate.allowed_merchants.length > 0 && (
              <div className="flex justify-between">
                <span className="text-sm text-muted-foreground">許可店舗</span>
                <span className="text-sm font-medium">
                  {intentMandate.allowed_merchants.join(", ")}
                </span>
              </div>
            )}
            {intentMandate.expires_at && (
              <div className="flex justify-between">
                <span className="text-sm text-muted-foreground">有効期限</span>
                <span className="text-sm font-medium">
                  {new Date(intentMandate.expires_at).toLocaleString("ja-JP")}
                </span>
              </div>
            )}
          </div>
        );

      case "cart":
        const cartMandate = mandate as CartMandate;
        return (
          <div className="space-y-3">
            <div className="flex justify-between">
              <span className="text-sm text-muted-foreground">店舗</span>
              <span className="text-sm font-medium">{cartMandate.merchant_id}</span>
            </div>
            <Separator />
            <div className="space-y-2">
              <span className="text-sm font-semibold">カート内容</span>
              {cartMandate.items?.map((item, index) => (
                <div key={index} className="flex justify-between text-sm">
                  <span className="text-muted-foreground">
                    {item.name} x {item.quantity}
                  </span>
                  <span className="font-medium">
                    {item.total_price?.currency} {parseFloat(item.total_price?.value || "0").toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
            <Separator />
            <div className="flex justify-between font-semibold">
              <span>合計</span>
              <span className="text-lg">
                {cartMandate.total_amount?.currency} {parseFloat(cartMandate.total_amount?.value || "0").toLocaleString()}
              </span>
            </div>
          </div>
        );

      case "payment":
        const paymentMandate = mandate as PaymentMandate;
        return (
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-sm text-muted-foreground">支払金額</span>
              <span className="text-sm font-medium text-lg">
                {paymentMandate.amount?.currency} {parseFloat(paymentMandate.amount?.value || "0").toLocaleString()}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-muted-foreground">支払先</span>
              <span className="text-sm font-medium">{paymentMandate.payee_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-muted-foreground">支払方法</span>
              <span className="text-sm font-medium">
                {paymentMandate.payment_method?.brand} •••• {paymentMandate.payment_method?.last4}
              </span>
            </div>
            {paymentMandate.risk_score !== undefined && (
              <div className="flex justify-between">
                <span className="text-sm text-muted-foreground">リスクスコア</span>
                <span className="text-sm font-medium">{paymentMandate.risk_score}/100</span>
              </div>
            )}
          </div>
        );

      default:
        return <p className="text-sm text-muted-foreground">Mandate情報が利用できません</p>;
    }
  };

  const getMandateTitle = () => {
    switch (mandate_type) {
      case "intent":
        return "購入意図の署名";
      case "cart":
        return "カートの署名";
      case "payment":
        return "支払いの署名";
      default:
        return "署名リクエスト";
    }
  };

  return (
    <Dialog open={true} onOpenChange={() => !isSigning && onCancel()}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-6 h-6 text-blue-500" />
            <DialogTitle>{getMandateTitle()}</DialogTitle>
          </div>
          <DialogDescription>
            この操作であなたのデバイスがこの{mandate_type === "intent" ? "購入意図" : mandate_type === "cart" ? "カート" : "支払い"}を承認します
          </DialogDescription>
        </DialogHeader>

        <div className="my-4">
          {renderMandateDetails()}
        </div>

        {error && (
          <div className="flex items-center gap-2 p-3 bg-destructive/10 text-destructive rounded-md">
            <AlertCircle className="w-4 h-4" />
            <p className="text-sm">{error}</p>
          </div>
        )}

        <DialogFooter>
          <Button
            variant="outline"
            onClick={onCancel}
            disabled={isSigning}
          >
            キャンセル
          </Button>
          <Button
            onClick={handleSign}
            disabled={isSigning}
          >
            {isSigning && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {isSigning ? "署名中..." : "Passkeyで署名"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
