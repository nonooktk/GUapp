import type { Metadata, Viewport } from "next";
import { Noto_Sans_JP } from "next/font/google";
import { cookies } from "next/headers";
import { CartProvider } from "@/components/CartProvider";
import Footer from "@/components/Footer";
import HeaderWithCart from "@/components/HeaderWithCart";
import { ToastProvider } from "@/components/Toast";
import { CART_TOKEN_COOKIE } from "@/lib/cookie";
import { getCategories, loadOrNull } from "@/lib/server/catalog";
import "./globals.css";

/**
 * 共通レイアウト（設計仕様書 6.2）。ヘッダー固定＋本文＋フッター。
 * カート点数は CartProvider が `GET /api/cart` で取得し HeaderWithCart のバッジに出す（UT-WEB-01）。
 * Cookie `cart_token` が無い訪問者にはカートを作らない（取得を省いて 0 を描く）。
 * オールメニュー（AT-07）のカテゴリ階層は GET /categories をここで取得して props で渡す。失敗時は null（メニュー側で案内を出し、ヘッダーは描く）。
 * Next.js 16 では `cookies()` が Promise なので await する。
 *
 * 書体はデザイン基準 v1 2.2 の Noto Sans JP（300/400/700）。`variable` で <html> に CSS 変数を付け、
 * globals.css の `--font-body` / `--font-heading` から参照する。日本語のサブセットは Google Fonts が unicode-range で自動分割する。
 */

const notoSansJP = Noto_Sans_JP({
  weight: ["300", "400", "700"],
  subsets: ["latin"],
  display: "swap",
  variable: "--font-noto-sans-jp",
});

export const metadata: Metadata = {
  title: "GU EC サイト",
  description: "GU EC サイト（P1 演習）",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const store = await cookies();
  const hasCartCookie = store.has(CART_TOKEN_COOKIE);
  const cats = await loadOrNull(getCategories(), "categories (layout)");

  return (
    <html lang="ja" className={`h-full antialiased ${notoSansJP.variable}`}>
      <body className="flex min-h-full flex-col bg-bg font-body text-fg">
        <ToastProvider>
          <CartProvider hasCartCookie={hasCartCookie}>
            <HeaderWithCart categories={cats?.categories ?? null} />
            <main id="main" className="mx-auto w-full max-w-page flex-1 px-4 py-6">
              {children}
            </main>
            <Footer />
          </CartProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
