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
import { registerPasskey } from "@/lib/webauthn";
import { Fingerprint, Loader2, CheckCircle2, AlertCircle } from "lucide-react";

interface PasskeyRegistrationProps {
  open: boolean;
  onRegistered: (userId: string, userName: string) => void;
  onCancel: () => void;
}

export function PasskeyRegistration({
  open,
  onRegistered,
  onCancel,
}: PasskeyRegistrationProps) {
  const [userId, setUserId] = useState("user_demo_001");
  const [userName, setUserName] = useState("デモユーザー");
  const [isRegistering, setIsRegistering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleRegister = async () => {
    if (!userId.trim() || !userName.trim()) {
      setError("ユーザーIDと名前を入力してください");
      return;
    }

    setIsRegistering(true);
    setError(null);

    try {
      const attestation = await registerPasskey(
        userId,
        userName,
        process.env.NEXT_PUBLIC_RP_ID || "localhost",
        process.env.NEXT_PUBLIC_RP_NAME || "AP2 Demo App v2"
      );

      console.log("Passkey registered:", attestation);

      // Credential Providerに登録情報を送信
      const credentialProviderUrl =
        process.env.NEXT_PUBLIC_CREDENTIAL_PROVIDER_URL || "http://localhost:8003";

      const registerResponse = await fetch(
        `${credentialProviderUrl}/register/passkey`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: userId,
            credential_id: attestation.rawId,
            attestation_object: attestation.attestationObject,
            transports: attestation.transports || [],
          }),
        }
      );

      if (!registerResponse.ok) {
        const errorData = await registerResponse.json();
        throw new Error(errorData.detail || "Passkey registration failed on server");
      }

      const registerData = await registerResponse.json();
      console.log("Passkey registered on server:", registerData);

      setSuccess(true);
      setTimeout(() => {
        onRegistered(userId, userName);
      }, 1500);
    } catch (err: any) {
      console.error("Passkey registration error:", err);
      setError(err.message || "Passkeyの登録に失敗しました");
      setIsRegistering(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={() => {}}>
      <DialogContent className="sm:max-w-[450px]" onInteractOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <div className="flex items-center gap-2">
            <Fingerprint className="w-6 h-6 text-blue-500" />
            <DialogTitle>Passkey登録</DialogTitle>
          </div>
          <DialogDescription>
            AP2 Shopping Agentを利用するには、Passkeyの登録が必要です
          </DialogDescription>
        </DialogHeader>

        {!success ? (
          <>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">ユーザーID</label>
                <Input
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                  placeholder="user_demo_001"
                  disabled={isRegistering}
                />
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">表示名</label>
                <Input
                  value={userName}
                  onChange={(e) => setUserName(e.target.value)}
                  placeholder="デモユーザー"
                  disabled={isRegistering}
                />
              </div>

              <div className="bg-muted p-3 rounded-md text-sm">
                <p className="text-muted-foreground">
                  💡 デモ用のユーザーIDが事前に入力されています。そのまま登録するか、別のIDを入力してください。
                </p>
              </div>
            </div>

            {error && (
              <div className="flex items-center gap-2 p-3 bg-destructive/10 text-destructive rounded-md">
                <AlertCircle className="w-4 h-4" />
                <p className="text-sm">{error}</p>
              </div>
            )}

            <DialogFooter>
              <Button onClick={handleRegister} disabled={isRegistering} className="w-full">
                {isRegistering && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isRegistering ? "登録中..." : "Passkeyを登録"}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <div className="flex flex-col items-center justify-center py-8">
            <CheckCircle2 className="w-16 h-16 text-green-500 mb-4" />
            <h3 className="text-lg font-semibold mb-2">登録完了！</h3>
            <p className="text-sm text-muted-foreground text-center">
              Passkeyの登録が完了しました。<br />
              Shopping Agentをご利用いただけます。
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
