"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Product } from "@/lib/types/chat";
import { Package, RefreshCw, Store } from "lucide-react";

export default function MerchantPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  // 商品一覧を取得
  const fetchProducts = async () => {
    setIsLoading(true);
    try {
      // TODO: 実際のAPIエンドポイントに接続
      // const response = await fetch('/api/products');
      // const data = await response.json();
      // setProducts(data.products || []);

      // 仮のデータ
      setProducts([
        {
          id: "prod_001",
          sku: "SHOE-RUN-001",
          name: "ナイキ エアズーム ペガサス 40",
          description: "高反発クッショニングで快適なランニングを実現",
          price: 1480000,
          inventory_count: 50,
        },
        {
          id: "prod_002",
          sku: "SHOE-RUN-002",
          name: "アディダス ウルトラブースト 22",
          description: "最高のエネルギーリターンを誇るランニングシューズ",
          price: 1980000,
          inventory_count: 30,
        },
      ]);
    } catch (error) {
      console.error("Failed to fetch products:", error);
    } finally {
      setIsLoading(false);
    }
  };

  // 在庫更新
  const updateInventory = async (productId: string, newCount: number) => {
    try {
      // TODO: 実際のAPIエンドポイントに接続
      // await fetch(`/api/products/${productId}`, {
      //   method: 'PATCH',
      //   body: JSON.stringify({ inventory_count: newCount })
      // });

      setProducts((prev) =>
        prev.map((p) =>
          p.id === productId ? { ...p, inventory_count: newCount } : p
        )
      );
    } catch (error) {
      console.error("Failed to update inventory:", error);
    }
  };

  useEffect(() => {
    fetchProducts();
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
              <p className="text-sm text-muted-foreground">在庫管理・商品管理</p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={fetchProducts} disabled={isLoading}>
            <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? "animate-spin" : ""}`} />
            更新
          </Button>
        </div>
      </header>

      {/* メインコンテンツ */}
      <main className="container max-w-6xl mx-auto p-6">
        <div className="grid gap-6">
          {/* 統計カード */}
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

          {/* 商品一覧 */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Package className="w-5 h-5" />
                商品一覧
              </CardTitle>
              <CardDescription>在庫数の変更・管理</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {products.map((product) => (
                  <div
                    key={product.id}
                    className="flex items-center justify-between p-4 border rounded-lg"
                  >
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
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* 将来の機能 */}
          <Card className="bg-muted/50">
            <CardHeader>
              <CardTitle className="text-sm font-medium">今後の機能</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="text-sm text-muted-foreground space-y-2">
                <li>• CartMandate署名機能</li>
                <li>• 注文履歴・トランザクション管理</li>
                <li>• 商品の追加・編集・削除</li>
                <li>• 売上統計・レポート</li>
              </ul>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}
