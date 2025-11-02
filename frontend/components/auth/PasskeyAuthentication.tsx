"use client";

import { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { signWithPasskey } from "@/lib/webauthn";
import { Fingerprint, Loader2, CheckCircle2, AlertCircle } from "lucide-react";

interface PasskeyAuthenticationProps {
  open: boolean;
  challenge: string;
  rpId: string;
  timeout: number;
  onAuthenticated: (attestation: any) => void;
  onError: (error: string) => void;
}

export function PasskeyAuthentication({
  open,
  challenge,
  rpId,
  timeout,
  onAuthenticated,
  onError,
}: PasskeyAuthenticationProps) {
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // モーダルが開いたら自動的に認証を開始
  useEffect(() => {
    if (open && !isAuthenticating && !success && !error) {
      handleAuthenticate();
    }
  }, [open]);

  const handleAuthenticate = async () => {
    setIsAuthenticating(true);
    setError(null);

    try {
      // Passkey認証を実行
      const attestation = await signWithPasskey(challenge, rpId);

      console.log("Passkey authentication successful:", attestation);

      setSuccess(true);

      // 少し待ってから成功を通知
      setTimeout(() => {
        onAuthenticated(attestation);
      }, 1000);
    } catch (err: any) {
      console.error("Passkey authentication error:", err);
      const errorMessage = err.message || "デバイス認証に失敗しました";
      setError(errorMessage);
      setIsAuthenticating(false);

      // エラーを親に通知
      setTimeout(() => {
        onError(errorMessage);
      }, 2000);
    }
  };

  const handleRetry = () => {
    setError(null);
    setSuccess(false);
    handleAuthenticate();
  };

  return (
    <Dialog open={open} onOpenChange={() => {}}>
      <DialogContent className="sm:max-w-[450px]" onInteractOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <div className="flex items-center gap-2">
            <Fingerprint className="w-6 h-6 text-blue-500" />
            <DialogTitle>デバイス認証</DialogTitle>
          </div>
          <DialogDescription>
            決済のセキュリティ確認のため、Passkey認証を実施します
          </DialogDescription>
        </DialogHeader>

        {!success && !error && (
          <div className="flex flex-col items-center justify-center py-8">
            <Loader2 className="w-16 h-16 text-blue-500 animate-spin mb-4" />
            <h3 className="text-lg font-semibold mb-2">認証中...</h3>
            <p className="text-sm text-muted-foreground text-center">
              デバイスの指示に従って認証を完了してください
            </p>
          </div>
        )}

        {success && (
          <div className="flex flex-col items-center justify-center py-8">
            <CheckCircle2 className="w-16 h-16 text-green-500 mb-4" />
            <h3 className="text-lg font-semibold mb-2">認証完了！</h3>
            <p className="text-sm text-muted-foreground text-center">
              デバイス認証が完了しました。<br />
              決済処理を続行します。
            </p>
          </div>
        )}

        {error && (
          <div className="flex flex-col items-center justify-center py-8">
            <AlertCircle className="w-16 h-16 text-destructive mb-4" />
            <h3 className="text-lg font-semibold mb-2">認証失敗</h3>
            <p className="text-sm text-muted-foreground text-center mb-4">
              {error}
            </p>
            <Button onClick={handleRetry} variant="outline">
              再試行
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
