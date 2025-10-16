"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import {
  Package,
  RefreshCw,
  Store,
  ShoppingCart,
  FileText,
  Settings,
  Plus,
  Trash2,
  Check,
  X,
  AlertCircle
} from "lucide-react";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";

type Product = {
  id: string;
  sku: string;
  name: string;
  description: string;
  price: number;
  inventory_count: number;
  metadata?: any;
};

type CartMandate = {
  id: string;
  payload: any;
  created_at: string;
};

type Transaction = {
  id: string;
  status: string;
  cart_id?: string;
  payment_id?: string;
  created_at: string;
  updated_at: string;
};

export default function MerchantPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [pendingCartMandates, setPendingCartMandates] = useState<CartMandate[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [autoSignMode, setAutoSignMode] = useState(true);
  const [showAddProductDialog, setShowAddProductDialog] = useState(false);
  const [showCartMandateDetail, setShowCartMandateDetail] = useState<CartMandate | null>(null);
  const [newProduct, setNewProduct] = useState({
    sku: "",
    name: "",
    description: "",
    price: 0,
    inventory_count: 0,
  });

  const merchantUrl = process.env.NEXT_PUBLIC_MERCHANT_URL || "http://localhost:8002";

  // 商品一覧を取得
  const fetchProducts = async () => {
    setIsLoading(true);
    try {
      const response = await fetch(`${merchantUrl}/products`);
      const data = await response.json();
      setProducts(data.products || []);
    } catch (error) {
      console.error("Failed to fetch products:", error);
    } finally {
      setIsLoading(false);
    }
  };

  // 署名待ちCartMandate取得
  const fetchPendingCartMandates = async () => {
    try {
      const response = await fetch(`${merchantUrl}/cart-mandates/pending`);
      const data = await response.json();
      setPendingCartMandates(data.pending_cart_mandates || []);
    } catch (error) {
      console.error("Failed to fetch pending cart mandates:", error);
    }
  };

  // トランザクション履歴取得
  const fetchTransactions = async () => {
    try {
      const response = await fetch(`${merchantUrl}/transactions`);
      const data = await response.json();
      setTransactions(data.transactions || []);
    } catch (error) {
      console.error("Failed to fetch transactions:", error);
    }
  };

  // 署名モード取得
  const fetchSignatureMode = async () => {
    try {
      const response = await fetch(`${merchantUrl}/settings/signature-mode`);
      const data = await response.json();
      setAutoSignMode(data.auto_sign_mode);
    } catch (error) {
      console.error("Failed to fetch signature mode:", error);
    }
  };

  // 署名モード切り替え
  const toggleSignatureMode = async (enabled: boolean) => {
    try {
      await fetch(`${merchantUrl}/settings/signature-mode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auto_sign_mode: enabled }),
      });
      setAutoSignMode(enabled);
    } catch (error) {
      console.error("Failed to update signature mode:", error);
    }
  };

  // CartMandate承認
  const approveCartMandate = async (id: string) => {
    try {
      await fetch(`${merchantUrl}/cart-mandates/${id}/approve`, {
        method: "POST",
      });
      fetchPendingCartMandates();
      setShowCartMandateDetail(null);
    } catch (error) {
      console.error("Failed to approve cart mandate:", error);
    }
  };

  // CartMandate却下
  const rejectCartMandate = async (id: string) => {
    try {
      await fetch(`${merchantUrl}/cart-mandates/${id}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "Manual rejection" }),
      });
      fetchPendingCartMandates();
      setShowCartMandateDetail(null);
    } catch (error) {
      console.error("Failed to reject cart mandate:", error);
    }
  };

  // 在庫更新
  const updateInventory = async (productId: string, newCount: number) => {
    try {
      await fetch(`${merchantUrl}/products/${productId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inventory_count: newCount }),
      });
      setProducts((prev) =>
        prev.map((p) =>
          p.id === productId ? { ...p, inventory_count: newCount } : p
        )
      );
    } catch (error) {
      console.error("Failed to update inventory:", error);
    }
  };

  // 商品追加
  const addProduct = async () => {
    try {
      const response = await fetch(`${merchantUrl}/products`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...newProduct,
          price: newProduct.price * 100, // 円→cents
        }),
      });
      const product = await response.json();
      setProducts((prev) => [...prev, product]);
      setShowAddProductDialog(false);
      setNewProduct({
        sku: "",
        name: "",
        description: "",
        price: 0,
        inventory_count: 0,
      });
    } catch (error) {
      console.error("Failed to add product:", error);
    }
  };

  // 商品削除
  const deleteProduct = async (productId: string) => {
    if (!confirm("本当にこの商品を削除しますか？")) return;

    try {
      await fetch(`${merchantUrl}/products/${productId}`, {
        method: "DELETE",
      });
      setProducts((prev) => prev.filter((p) => p.id !== productId));
    } catch (error) {
      console.error("Failed to delete product:", error);
    }
  };

  useEffect(() => {
    fetchProducts();
    fetchPendingCartMandates();
    fetchTransactions();
    fetchSignatureMode();

    // 5秒ごとに署名待ちとトランザクションを更新
    const interval = setInterval(() => {
      fetchPendingCartMandates();
      fetchTransactions();
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-background">
      {/* ヘッダー */}
      <header className="border-b bg-card p-4">
        <div className="container max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Store className="w-8 h-8 text-primary" />
            <div>
              <h1 className="text-xl font-semibold">Merchant Dashboard</h1>
              <p className="text-sm text-muted-foreground">
                在庫管理・注文管理・署名設定
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={autoSignMode ? "default" : "secondary"}>
              {autoSignMode ? "自動署名" : "手動署名"}
            </Badge>
            {pendingCartMandates.length > 0 && !autoSignMode && (
              <Badge variant="destructive">
                {pendingCartMandates.length}件の署名待ち
              </Badge>
            )}
          </div>
        </div>
      </header>

      {/* メインコンテンツ */}
      <main className="container max-w-6xl mx-auto p-6">
        <Tabs defaultValue="products" className="w-full">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="products">
              <Package className="w-4 h-4 mr-2" />
              商品管理
            </TabsTrigger>
            <TabsTrigger value="pending">
              <ShoppingCart className="w-4 h-4 mr-2" />
              署名待ち
              {pendingCartMandates.length > 0 && (
                <Badge variant="destructive" className="ml-2">
                  {pendingCartMandates.length}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="transactions">
              <FileText className="w-4 h-4 mr-2" />
              注文履歴
            </TabsTrigger>
            <TabsTrigger value="settings">
              <Settings className="w-4 h-4 mr-2" />
              設定
            </TabsTrigger>
          </TabsList>

          {/* 商品管理タブ */}
          <TabsContent value="products" className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-bold">商品一覧</h2>
                <p className="text-muted-foreground">
                  在庫数の変更・商品の追加・削除
                </p>
              </div>
              <div className="flex gap-2">
                <Button onClick={fetchProducts} variant="outline" size="sm">
                  <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? "animate-spin" : ""}`} />
                  更新
                </Button>
                <Button onClick={() => setShowAddProductDialog(true)} size="sm">
                  <Plus className="w-4 h-4 mr-2" />
                  商品追加
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Card>
                <CardHeader className="pb-3">
                  <CardDescription>総商品数</CardDescription>
                  <CardTitle className="text-3xl">{products.length}</CardTitle>
                </CardHeader>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardDescription>総在庫数</CardDescription>
                  <CardTitle className="text-3xl">
                    {products.reduce((sum, p) => sum + p.inventory_count, 0)}
                  </CardTitle>
                </CardHeader>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardDescription>在庫切れ商品</CardDescription>
                  <CardTitle className="text-3xl text-destructive">
                    {products.filter((p) => p.inventory_count === 0).length}
                  </CardTitle>
                </CardHeader>
              </Card>
            </div>

            <div className="space-y-4">
              {products.map((product) => (
                <Card key={product.id}>
                  <CardContent className="p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex-1">
                        <h3 className="font-semibold">{product.name}</h3>
                        <p className="text-sm text-muted-foreground">
                          SKU: {product.sku}
                        </p>
                        <p className="text-sm">
                          価格: ¥{(product.price / 100).toLocaleString()}
                        </p>
                      </div>

                      <div className="flex items-center gap-3">
                        <div className="text-right">
                          <p className="text-sm text-muted-foreground">在庫数</p>
                          <div className="flex items-center gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() =>
                                updateInventory(
                                  product.id,
                                  Math.max(0, product.inventory_count - 1)
                                )
                              }
                            >
                              -
                            </Button>
                            <Input
                              type="number"
                              value={product.inventory_count}
                              onChange={(e) =>
                                updateInventory(
                                  product.id,
                                  parseInt(e.target.value) || 0
                                )
                              }
                              className="w-20 text-center"
                            />
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() =>
                                updateInventory(
                                  product.id,
                                  product.inventory_count + 1
                                )
                              }
                            >
                              +
                            </Button>
                          </div>
                        </div>

                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => deleteProduct(product.id)}
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </TabsContent>

          {/* 署名待ちタブ */}
          <TabsContent value="pending" className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-bold">署名待ちCartMandate</h2>
                <p className="text-muted-foreground">
                  手動承認が必要な注文
                </p>
              </div>
              <Button onClick={fetchPendingCartMandates} variant="outline" size="sm">
                <RefreshCw className="w-4 h-4 mr-2" />
                更新
              </Button>
            </div>

            {!autoSignMode && pendingCartMandates.length === 0 && (
              <Card>
                <CardContent className="p-8 text-center">
                  <Check className="w-12 h-12 mx-auto mb-4 text-green-500" />
                  <p className="text-lg font-semibold">署名待ちの注文はありません</p>
                  <p className="text-sm text-muted-foreground mt-2">
                    新しい注文が来たらここに表示されます
                  </p>
                </CardContent>
              </Card>
            )}

            {autoSignMode && (
              <Card className="border-yellow-500">
                <CardContent className="p-6">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="w-5 h-5 text-yellow-500 mt-0.5" />
                    <div>
                      <p className="font-semibold">自動署名モードが有効です</p>
                      <p className="text-sm text-muted-foreground mt-1">
                        全ての注文は自動的に署名されます。手動承認を行いたい場合は、設定タブで手動署名モードに切り替えてください。
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}

            <div className="space-y-4">
              {pendingCartMandates.map((mandate) => (
                <Card key={mandate.id} className="border-orange-500">
                  <CardContent className="p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex-1">
                        <h3 className="font-semibold">CartMandate {mandate.id}</h3>
                        <p className="text-sm text-muted-foreground">
                          作成日時: {new Date(mandate.created_at).toLocaleString("ja-JP")}
                        </p>
                        <p className="text-sm mt-2">
                          合計: {mandate.payload?.total?.currency} ¥
                          {parseFloat(mandate.payload?.total?.value || "0").toLocaleString()}
                        </p>
                        <p className="text-sm text-muted-foreground">
                          商品数: {mandate.payload?.items?.length || 0}件
                        </p>
                      </div>

                      <div className="flex gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setShowCartMandateDetail(mandate)}
                        >
                          詳細
                        </Button>
                        <Button
                          variant="default"
                          size="sm"
                          onClick={() => approveCartMandate(mandate.id)}
                        >
                          <Check className="w-4 h-4 mr-1" />
                          承認
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => rejectCartMandate(mandate.id)}
                        >
                          <X className="w-4 h-4 mr-1" />
                          却下
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </TabsContent>

          {/* 注文履歴タブ */}
          <TabsContent value="transactions" className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-bold">注文履歴</h2>
                <p className="text-muted-foreground">
                  全トランザクション一覧
                </p>
              </div>
              <Button onClick={fetchTransactions} variant="outline" size="sm">
                <RefreshCw className="w-4 h-4 mr-2" />
                更新
              </Button>
            </div>

            <div className="space-y-4">
              {transactions.length === 0 && (
                <Card>
                  <CardContent className="p-8 text-center">
                    <FileText className="w-12 h-12 mx-auto mb-4 text-muted-foreground opacity-50" />
                    <p className="text-lg font-semibold">トランザクション履歴がありません</p>
                    <p className="text-sm text-muted-foreground mt-2">
                      注文が完了するとここに表示されます
                    </p>
                  </CardContent>
                </Card>
              )}

              {transactions.map((transaction) => (
                <Card key={transaction.id}>
                  <CardContent className="p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex-1">
                        <h3 className="font-semibold">Transaction {transaction.id}</h3>
                        <p className="text-sm text-muted-foreground">
                          作成: {new Date(transaction.created_at).toLocaleString("ja-JP")}
                        </p>
                        {transaction.cart_id && (
                          <p className="text-sm text-muted-foreground">
                            Cart ID: {transaction.cart_id}
                          </p>
                        )}
                      </div>

                      <Badge
                        variant={
                          transaction.status === "captured"
                            ? "default"
                            : transaction.status === "failed"
                            ? "destructive"
                            : "secondary"
                        }
                      >
                        {transaction.status}
                      </Badge>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </TabsContent>

          {/* 設定タブ */}
          <TabsContent value="settings" className="space-y-4">
            <div>
              <h2 className="text-2xl font-bold">設定</h2>
              <p className="text-muted-foreground">
                署名モードと店舗設定
              </p>
            </div>

            <Card>
              <CardHeader>
                <CardTitle>署名モード</CardTitle>
                <CardDescription>
                  注文の自動署名または手動承認を選択
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="auto-sign" className="text-base">
                      自動署名モード
                    </Label>
                    <p className="text-sm text-muted-foreground">
                      全ての注文を自動的に署名・承認します
                    </p>
                  </div>
                  <Switch
                    id="auto-sign"
                    checked={autoSignMode}
                    onCheckedChange={toggleSignatureMode}
                  />
                </div>

                <Separator />

                <div className="space-y-2">
                  <h4 className="font-semibold">モードの説明</h4>
                  <div className="space-y-2 text-sm">
                    <div className="flex items-start gap-2">
                      <Check className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                      <div>
                        <p className="font-medium">自動署名モード（推奨）</p>
                        <p className="text-muted-foreground">
                          在庫確認とバリデーション後、即座に署名します。効率的で高速です。
                        </p>
                      </div>
                    </div>
                    <div className="flex items-start gap-2">
                      <AlertCircle className="w-4 h-4 text-yellow-500 mt-0.5 flex-shrink-0" />
                      <div>
                        <p className="font-medium">手動署名モード</p>
                        <p className="text-muted-foreground">
                          各注文を個別に確認・承認します。高額商品や慎重な対応が必要な場合に使用します。
                        </p>
                      </div>
                    </div>
                  </div>
                </div>

                {!autoSignMode && pendingCartMandates.length > 0 && (
                  <div className="p-4 bg-orange-50 dark:bg-orange-950 border border-orange-200 dark:border-orange-800 rounded-md">
                    <div className="flex items-center gap-2">
                      <AlertCircle className="w-4 h-4 text-orange-500" />
                      <p className="text-sm font-semibold text-orange-900 dark:text-orange-100">
                        {pendingCartMandates.length}件の署名待ち注文があります
                      </p>
                    </div>
                    <p className="text-sm text-orange-700 dark:text-orange-300 mt-1">
                      署名待ちタブで承認または却下してください。
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </main>

      {/* 商品追加ダイアログ */}
      <Dialog open={showAddProductDialog} onOpenChange={setShowAddProductDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新しい商品を追加</DialogTitle>
            <DialogDescription>
              商品情報を入力してください
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="sku">SKU *</Label>
              <Input
                id="sku"
                value={newProduct.sku}
                onChange={(e) => setNewProduct({ ...newProduct, sku: e.target.value })}
                placeholder="SHOE-001"
              />
            </div>
            <div>
              <Label htmlFor="name">商品名 *</Label>
              <Input
                id="name"
                value={newProduct.name}
                onChange={(e) => setNewProduct({ ...newProduct, name: e.target.value })}
                placeholder="ナイキ エアズーム"
              />
            </div>
            <div>
              <Label htmlFor="description">説明 *</Label>
              <Input
                id="description"
                value={newProduct.description}
                onChange={(e) => setNewProduct({ ...newProduct, description: e.target.value })}
                placeholder="高性能ランニングシューズ"
              />
            </div>
            <div>
              <Label htmlFor="price">価格（円） *</Label>
              <Input
                id="price"
                type="number"
                value={newProduct.price}
                onChange={(e) => setNewProduct({ ...newProduct, price: parseFloat(e.target.value) || 0 })}
                placeholder="14800"
              />
            </div>
            <div>
              <Label htmlFor="inventory">在庫数 *</Label>
              <Input
                id="inventory"
                type="number"
                value={newProduct.inventory_count}
                onChange={(e) => setNewProduct({ ...newProduct, inventory_count: parseInt(e.target.value) || 0 })}
                placeholder="50"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddProductDialog(false)}>
              キャンセル
            </Button>
            <Button onClick={addProduct} disabled={!newProduct.sku || !newProduct.name}>
              追加
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* CartMandate詳細ダイアログ */}
      <Dialog open={!!showCartMandateDetail} onOpenChange={() => setShowCartMandateDetail(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>CartMandate詳細</DialogTitle>
            <DialogDescription>
              注文内容を確認して承認または却下してください
            </DialogDescription>
          </DialogHeader>
          {showCartMandateDetail && (
            <div className="space-y-4">
              <div>
                <h4 className="font-semibold mb-2">基本情報</h4>
                <div className="space-y-1 text-sm">
                  <p><span className="text-muted-foreground">ID:</span> {showCartMandateDetail.id}</p>
                  <p><span className="text-muted-foreground">作成日時:</span> {new Date(showCartMandateDetail.created_at).toLocaleString("ja-JP")}</p>
                  <p><span className="text-muted-foreground">店舗:</span> {showCartMandateDetail.payload?.merchant_name}</p>
                </div>
              </div>

              <Separator />

              <div>
                <h4 className="font-semibold mb-2">注文商品</h4>
                <div className="space-y-2">
                  {showCartMandateDetail.payload?.items?.map((item: any, index: number) => (
                    <div key={index} className="flex justify-between text-sm p-2 bg-muted rounded">
                      <span>{item.name} x {item.quantity}</span>
                      <span className="font-medium">
                        {item.total_price?.currency} ¥{parseFloat(item.total_price?.value || "0").toLocaleString()}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <Separator />

              <div className="flex justify-between font-semibold text-lg">
                <span>合計</span>
                <span>
                  {showCartMandateDetail.payload?.total?.currency} ¥
                  {parseFloat(showCartMandateDetail.payload?.total?.value || "0").toLocaleString()}
                </span>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button
              variant="destructive"
              onClick={() => showCartMandateDetail && rejectCartMandate(showCartMandateDetail.id)}
            >
              <X className="w-4 h-4 mr-2" />
              却下
            </Button>
            <Button
              variant="default"
              onClick={() => showCartMandateDetail && approveCartMandate(showCartMandateDetail.id)}
            >
              <Check className="w-4 h-4 mr-2" />
              承認
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
