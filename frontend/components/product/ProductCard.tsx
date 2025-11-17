import Image from "next/image";
import { Product } from "@/lib/types/chat";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ShoppingCart } from "lucide-react";

interface ProductCardProps {
  product: Product;
  onAddToCart?: (product: Product) => void;
}

export function ProductCard({ product, onAddToCart }: ProductCardProps) {
  const formattedPrice = (product.price / 100).toLocaleString("ja-JP", {
    style: "currency",
    currency: "JPY",
  });

  // 画像URLを取得（metadata.image_urlまたはproduct.image_url）
  const imageUrl = product.metadata?.image_url || product.image_url || "https://placehold.co/400x400/EEE/999?text=No+Image";

  // ローカルパス（/assets/...）の場合は最適化をスキップ
  const isLocalPath = imageUrl.startsWith("/");

  return (
    <Card className="flex flex-col h-full" data-testid={`product-card-${product.id}`}>
      <CardContent className="flex-1 p-4">
        <div className="aspect-square bg-muted rounded-md mb-3 overflow-hidden relative">
          <Image
            src={imageUrl}
            alt={product.name}
            fill
            className="object-contain"
            sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
            unoptimized={isLocalPath}
            priority={false}
            data-testid={`product-image-${product.id}`}
          />
        </div>
        <h3 className="font-semibold text-sm mb-1 line-clamp-2" data-testid={`product-name-${product.id}`}>{product.name}</h3>
        <p className="text-xs text-muted-foreground line-clamp-2 mb-2" data-testid={`product-description-${product.id}`}>
          {product.description}
        </p>
        <p className="text-lg font-bold" data-testid={`product-price-${product.id}`}>{formattedPrice}</p>
        {product.inventory_count !== undefined && (
          <p className="text-xs text-muted-foreground mt-1" data-testid={`product-inventory-${product.id}`}>
            在庫: {product.inventory_count}点
          </p>
        )}
      </CardContent>
      <CardFooter className="p-4 pt-0">
        <Button
          className="w-full"
          size="sm"
          onClick={() => onAddToCart?.(product)}
          disabled={product.inventory_count === 0}
          data-testid={`add-to-cart-button-${product.id}`}
        >
          <ShoppingCart className="w-4 h-4 mr-2" />
          カートに追加
        </Button>
      </CardFooter>
    </Card>
  );
}
