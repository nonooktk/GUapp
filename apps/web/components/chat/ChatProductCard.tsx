import Link from "next/link";
import Price from "@/components/Price";
import { imageUrl } from "@/lib/image";
import type { ChatProduct } from "@/lib/types";

/**
 * チャットの商品カード（設計仕様書 P2 追補d 6.2・DS-PRC-029-3、テスト UT-WEB-AI-05）。
 * 名称・税込価格・画像・在庫切れは **api が DB から出した値だけ**を描く（価格は `Price`＝`formatYen` の整形）。
 * 提案理由（`reason`）だけが LLM の文章。React の既定のエスケープだけで描き、HTML として解釈しない。
 * リンクは `/products/{id}` を組み立てたものだけ（LLM の文章に含まれるリンクは使わない）。
 */

export interface ChatProductCardProps {
  product: ChatProduct;
  imageBaseUrl: string;
  /** カードを押したとき（375px のシートを閉じるなど） */
  onNavigate?: () => void;
}

export default function ChatProductCard({ product, imageBaseUrl, onNavigate }: ChatProductCardProps) {
  const src = imageUrl(imageBaseUrl, product.image_path);
  return (
    <Link
      href={`/products/${product.id}`}
      onClick={onNavigate}
      className="flex gap-3 rounded-sm border border-line bg-bg p-2 hover:bg-line/40"
    >
      <div className="relative aspect-[3/4] w-16 shrink-0 overflow-hidden rounded-sm bg-line/50">
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element -- プレースホルダー PNG を素直に表示（ProductCard と同じ）
          <img src={src} alt={product.name} loading="lazy" className="size-full object-cover" />
        ) : (
          <span className="flex size-full items-center justify-center text-xs text-fg-muted" aria-label={`${product.name}（画像なし）`}>
            NO IMAGE
          </span>
        )}
        {product.sold_out && (
          <span className="absolute left-1 top-1 rounded-pill bg-badge px-1.5 py-0.5 text-xs font-bold text-primary-fg">在庫切れ</span>
        )}
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        <p className="line-clamp-2 break-words text-sm font-light text-fg">{product.name}</p>
        {product.sold_out ? (
          <p className="text-base font-bold text-fg-muted">在庫切れ</p>
        ) : (
          <Price amount={product.price_incl_tax} taxNote className="block text-base font-bold tracking-heading text-fg" />
        )}
        {product.reason && <p className="break-words text-xs text-fg-muted">{product.reason}</p>}
      </div>
    </Link>
  );
}
