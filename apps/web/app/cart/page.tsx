import CartView from "@/components/CartView";
import { getCartFromCookie, getImageBaseUrl, getPublicSettings, loadOrNull } from "@/lib/server/catalog";
import type { Cart } from "@/lib/types";

/**
 * カート DS-SCR-004（設計仕様書 6.6、テスト AT-04・ST-F009-01〜05）。
 * Cookie `cart_token` があれば Server Component が FastAPI から初期表示を取得し、以降の変更は CartView（クライアント）が
 * BFF 経由で行う。Cookie が無ければ空カート（描画中は Cookie を発行できないため、作成は追加操作に任せる）。
 * サーバー取得に失敗したとき（FastAPI 停止・未知トークン等）はクライアントで取り直す。
 */

export const dynamic = "force-dynamic";

const FALLBACK_FREE_SHIPPING_THRESHOLD = 4990;

export default async function CartPage() {
  let initialCart: Cart | null = null;
  let refetchOnMount = false;
  try {
    const result = await getCartFromCookie();
    if (result === null) {
      initialCart = null; // Cookie 無し = カート未作成
    } else if (result.ok) {
      initialCart = result.data;
    } else {
      refetchOnMount = true; // 未知トークン等。Route Handler 経由で Cookie を更新しつつ取り直す
    }
  } catch {
    refetchOnMount = true; // FastAPI 停止。クライアント側でも失敗すれば「読み込めませんでした」
  }

  const settings = await loadOrNull(getPublicSettings(), "settings/public");
  const imageBaseUrl = getImageBaseUrl();

  // 見出し（点数）は CartView 側で描き、数量変更・削除に追従させる
  return (
    <CartView
      initialCart={initialCart}
      imageBaseUrl={imageBaseUrl}
      refetchOnMount={refetchOnMount}
      freeShippingThreshold={settings?.free_shipping_threshold ?? FALLBACK_FREE_SHIPPING_THRESHOLD}
    />
  );
}
