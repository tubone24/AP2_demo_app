"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CreditCard, Trash2, ShieldAlert, Loader2 } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

/**
 * 支払い方法一覧コンポーネント（AP2完全準拠）
 */

interface PaymentMethod {
  id: string;
  type: string;
  brand: string;
  last4: string;
  display_name: string;
  requires_step_up?: boolean;
  stepup_method?: string;
  created_at: string;
}

interface PaymentMethodListProps {
  userId: string;
  refreshKey: number;
  onRefresh: () => void;
}

export function PaymentMethodList({
  userId,
  refreshKey,
  onRefresh,
}: PaymentMethodListProps) {
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethod[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<PaymentMethod | null>(null);

  // 支払い方法一覧を取得（AP2 GET /payment-methods）
  const fetchPaymentMethods = async () => {
    setLoading(true);
    try {
      const cpUrl = process.env.NEXT_PUBLIC_CREDENTIAL_PROVIDER_URL || "http://localhost:8003";
      const response = await fetch(`${cpUrl}/payment-methods?user_id=${userId}`);

      if (!response.ok) {
        throw new Error("Failed to fetch payment methods");
      }

      const data = await response.json();
      setPaymentMethods(data.payment_methods || []);
    } catch (error) {
      console.error("Failed to fetch payment methods:", error);
      setPaymentMethods([]);
    } finally {
      setLoading(false);
    }
  };

  // 支払い方法を削除（AP2 DELETE /payment-methods/{id}）
  const handleDelete = async (paymentMethodId: string) => {
    setDeleting(paymentMethodId);
    try {
      const cpUrl = process.env.NEXT_PUBLIC_CREDENTIAL_PROVIDER_URL || "http://localhost:8003";
      const response = await fetch(`${cpUrl}/payment-methods/${paymentMethodId}`, {
        method: "DELETE",
      });

      if (!response.ok) {
        throw new Error("Failed to delete payment method");
      }

      // 削除成功後、リストを再取得
      await fetchPaymentMethods();
      onRefresh();
    } catch (error) {
      console.error("Failed to delete payment method:", error);
      alert("支払い方法の削除に失敗しました");
    } finally {
      setDeleting(null);
      setDeleteConfirm(null);
    }
  };

  useEffect(() => {
    fetchPaymentMethods();
  }, [userId, refreshKey]);

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (paymentMethods.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-center">
          <CreditCard className="w-12 h-12 text-muted-foreground mb-3" />
          <p className="text-sm text-muted-foreground">
            登録されている支払い方法がありません
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            「支払い方法を追加」ボタンから登録してください
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <div className="grid gap-4 md:grid-cols-2">
        {paymentMethods.map((method) => (
          <Card key={method.id} className="relative">
            <CardContent className="pt-6">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-2">
                  <CreditCard className="w-5 h-5 text-blue-500" />
                  <div>
                    <p className="font-semibold">{method.display_name}</p>
                    <p className="text-xs text-muted-foreground">
                      {method.brand} •••• {method.last4}
                    </p>
                  </div>
                </div>
                {method.requires_step_up && (
                  <Badge variant="secondary" className="text-xs">
                    <ShieldAlert className="w-3 h-3 mr-1" />
                    3D Secure
                  </Badge>
                )}
              </div>

              {method.requires_step_up && (
                <div className="text-xs text-muted-foreground bg-muted/30 p-2 rounded">
                  このカードは決済時に{method.stepup_method || "追加認証"}が必要です
                </div>
              )}
            </CardContent>
            <CardFooter>
              <Button
                variant="destructive"
                size="sm"
                className="w-full"
                onClick={() => setDeleteConfirm(method)}
                disabled={deleting === method.id}
              >
                {deleting === method.id ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    削除中...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-4 h-4 mr-2" />
                    削除
                  </>
                )}
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>

      {/* 削除確認ダイアログ */}
      <AlertDialog
        open={deleteConfirm !== null}
        onOpenChange={() => setDeleteConfirm(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>支払い方法を削除しますか？</AlertDialogTitle>
            <AlertDialogDescription>
              {deleteConfirm?.display_name} を削除します。
              この操作は取り消せません。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>キャンセル</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteConfirm && handleDelete(deleteConfirm.id)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              削除する
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
