"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AddPaymentMethodForm } from "@/components/payment/AddPaymentMethodForm";
import { PaymentMethodList } from "@/components/payment/PaymentMethodList";
import { CreditCard, Plus, ArrowLeft } from "lucide-react";
import { isAuthenticated, getCurrentUser } from "@/lib/passkey";

/**
 * 支払い方法管理ページ（AP2完全準拠）
 *
 * - 支払い方法一覧の表示
 * - 新しい支払い方法の追加
 * - 既存の支払い方法の編集・削除
 */
export default function PaymentMethodsPage() {
  const router = useRouter();
  const [userId, setUserId] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  // AP2完全準拠: JWT認証チェック（Layer 1）
  useEffect(() => {
    // JWT認証状態をチェック
    if (!isAuthenticated()) {
      // 未認証の場合はログイン画面へリダイレクト
      router.push('/auth/login');
      return;
    }

    // 現在のユーザー情報を取得
    const user = getCurrentUser();
    if (user) {
      setUserId(user.id);
    }
  }, [router]);

  // 支払い方法追加完了時の処理
  const handlePaymentMethodAdded = () => {
    setShowAddForm(false);
    setRefreshKey((prev) => prev + 1); // リストを再読み込み
  };

  if (!userId) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p>Loading...</p>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl">
      {/* ヘッダー */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => router.push("/chat")}
          >
            <ArrowLeft className="w-5 h-5" />
          </Button>
          <div className="flex items-center gap-2">
            <CreditCard className="w-6 h-6 text-blue-500" />
            <h1 className="text-2xl font-bold">支払い方法の管理</h1>
          </div>
        </div>
        <Button onClick={() => setShowAddForm(true)}>
          <Plus className="w-4 h-4 mr-2" />
          支払い方法を追加
        </Button>
      </div>

      {/* 説明カード */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">AP2完全準拠の支払い方法管理</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          <ul className="space-y-1">
            <li>• 複数の支払い方法を登録・管理できます</li>
            <li>• American Expressカードは自動的に3D Secure（Step-up認証）が有効になります</li>
            <li>• 登録した支払い方法は、チャット画面での購入時に選択できます</li>
          </ul>
        </CardContent>
      </Card>

      {/* 支払い方法一覧 */}
      <PaymentMethodList
        userId={userId}
        refreshKey={refreshKey}
        onRefresh={() => setRefreshKey((prev) => prev + 1)}
      />

      {/* 支払い方法追加フォーム */}
      <AddPaymentMethodForm
        open={showAddForm}
        userId={userId}
        credentialProviderUrl={process.env.NEXT_PUBLIC_CREDENTIAL_PROVIDER_URL || "http://localhost:8003"}
        onAdded={handlePaymentMethodAdded}
        onSkip={() => setShowAddForm(false)}
      />
    </div>
  );
}
