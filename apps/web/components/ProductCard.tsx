import Link from "next/link";
import Price from "@/components/Price";
import { imageUrl } from "@/lib/image";

/**
 * 商品カード（設計仕様書 6.3・6.4）。一覧・ホーム・関連商品で共用。
 * 画像は `next/image` を使わず `<img>`＋`object-cover`（プレースホルダー PNG を素直に出すため）。
 * `sold_out` なら価格の代わりに「在庫切れ」（F-007）。
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
    <Link
      href={`/products/${id}`}
      className="group block rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900"
    >
      <div className="relative aspect-[3/4] overflow-hidden rounded-lg bg-gray-100">
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element -- プレースホルダー PNG を素直に表示（README 参照）
          <img src={src} alt={name} loading="lazy" className="size-full object-cover transition group-hover:opacity-90" />
        ) : (
          <span className="flex size-full items-center justify-center text-xs text-gray-400" aria-label={`${name}（画像なし）`}>
            NO IMAGE
          </span>
        )}
        {soldOut && (
          <span className="absolute left-2 top-2 rounded bg-gray-900/80 px-2 py-0.5 text-xs font-bold text-white">
            在庫切れ
          </span>
        )}
      </div>
      <div className="mt-2 space-y-0.5">
        <p className="line-clamp-2 text-sm text-gray-900">{name}</p>
        {soldOut ? (
          <p className="text-sm font-bold text-gray-500">在庫切れ</p>
        ) : (
          <Price amount={price} className="text-sm font-bold" />
        )}
        {colors && colors.length > 0 && (
          <p className="text-xs text-gray-500">{colors.length} 色</p>
        )}
      </div>
    </Link>
  );
}
