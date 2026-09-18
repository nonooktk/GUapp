import Link from "next/link";
import Price from "@/components/Price";
import { imageUrl } from "@/lib/image";

/**
 * 商品カード（設計仕様書 6.3・6.4、デザイン基準 v1 3 章「商品カード」）。一覧・ホーム・関連商品で共用。
 * 画像は 3:4・角丸 8px。名称は --text-base・weight 300・最大 2 行、価格は --text-lg・700。
 * 画像は `next/image` を使わず `<img>`＋`object-cover`（プレースホルダー PNG を素直に出すため）。
 * `sold_out` なら画像左上に --color-badge のバッジ、価格の代わりに「在庫切れ」（F-007）。
 */

export interface ProductCardProps {
  id: number;
  name: string;
  price: number;
  imagePath: string | null;
  imageBaseUrl: string;
  soldOut: boolean;
  colors?: string[];
}

export default function ProductCard({ id, name, price, imagePath, imageBaseUrl, soldOut, colors }: ProductCardProps) {
  const src = imageUrl(imageBaseUrl, imagePath);
  return (
    <Link href={`/products/${id}`} className="group block rounded-sm">
      <div className="relative aspect-[3/4] overflow-hidden rounded-sm bg-line/50">
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element -- プレースホルダー PNG を素直に表示（README 参照）
          <img src={src} alt={name} loading="lazy" className="size-full object-cover transition group-hover:opacity-90" />
        ) : (
          <span className="flex size-full items-center justify-center text-xs text-fg-muted" aria-label={`${name}（画像なし）`}>
            NO IMAGE
          </span>
        )}
        {soldOut && (
          <span className="absolute left-2 top-2 rounded-pill bg-badge px-2 py-0.5 text-xs font-bold text-primary-fg">在庫切れ</span>
        )}
      </div>
      <div className="mt-2 space-y-1">
        <p className="line-clamp-2 text-base font-light text-fg">{name}</p>
        {soldOut ? (
          <p className="text-lg font-bold text-fg-muted">在庫切れ</p>
        ) : (
          <Price amount={price} className="block text-lg font-bold tracking-heading text-fg" />
        )}
        {colors && colors.length > 0 && <p className="text-xs text-fg-muted">{colors.length} 色</p>}
      </div>
    </Link>
  );
}
