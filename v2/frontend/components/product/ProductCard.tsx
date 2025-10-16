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

  return (
    <Card className="flex flex-col h-full">
      <CardContent className="flex-1 p-4">
        <div className="aspect-square bg-muted rounded-md mb-3 flex items-center justify-center">
          <span className="text-4xl text-muted-foreground">👟</span>
        </div>
        <h3 className="font-semibold text-sm mb-1 line-clamp-2">{product.name}</h3>
        <p className="text-xs text-muted-foreground line-clamp-2 mb-2">
          {product.description}
        </p>
        <p className="text-lg font-bold">{formattedPrice}</p>
        {product.inventory_count !== undefined && (
          <p className="text-xs text-muted-foreground mt-1">
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
        >
          <ShoppingCart className="w-4 h-4 mr-2" />
          カートに追加
        </Button>
      </CardFooter>
    </Card>
  );
}
