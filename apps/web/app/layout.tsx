import type { Metadata, Viewport } from "next";
import { Noto_Sans_JP } from "next/font/google";
import { cookies, headers } from "next/headers";
import { CartProvider } from "@/components/CartProvider";
import ChatLauncher from "@/components/chat/ChatLauncher";
import ChatPanel from "@/components/chat/ChatPanel";
import { ChatProvider } from "@/components/chat/ChatProvider";
import DemoPeriodBanner from "@/components/DemoPeriodBanner";
import Footer from "@/components/Footer";
import HeaderWithCart from "@/components/HeaderWithCart";
import { ToastProvider } from "@/components/Toast";
import { ADMIN_AREA_HEADER } from "@/lib/admin-types";
import { CART_TOKEN_COOKIE, SESSION_COOKIE } from "@/lib/cookie";
import { parseDemoPublicUntil } from "@/lib/demo-banner";
import { getCategories, getImageBaseUrl, loadOrNull } from "@/lib/server/catalog";
import "./globals.css";

/**
 * 共通レイアウト（設計仕様書 6.2）。ヘッダー固定＋本文＋フッター。
 * カート点数は CartProvider が `GET /api/cart` で取得し HeaderWithCart のバッジに出す（UT-WEB-01）。
 * Cookie `cart_token` が無い訪問者にはカートを作らない（取得を省いて 0 を描く）。
 * オールメニュー（AT-07）のカテゴリ階層は GET /categories をここで取得して props で渡す。失敗時は null（メニュー側で案内を出し、ヘッダーは描く）。
 * 会員アイコンは Cookie `sid` の有無だけで「ログイン」「マイページ」を切り替える（DS-DEC-86。FastAPI は呼ばない。失効した `sid` が
 * 残っていても、マイページを開いた時点で 401 → /login?next=/mypage へ移る）。Server Component は Cookie を発行・削除できないので読み取りだけ。
 * Next.js 16 では `cookies()` が Promise なので await する。
 *
 * 管理画面（P2 追補c DS-DEC-122・UT-WEB-52）: `proxy.ts` が `/admin` 配下のリクエストにだけ付けるリクエストヘッダー `x-admin-area: 1` を読み、
 * 値が `1` のときだけ顧客向けのヘッダー・フッター・カート・カテゴリの取得（GET /categories）・期間限定公開の帯を省く
 * （`html`／`body`／フォント／トーストだけ残す）。それ以外（ヘッダー無し・`0`・`1` 以外）は従来どおり顧客向けの枠を出す。
 * `/admin` 配下の見出し・メニューは `app/admin/layout.tsx` が出す。
 *
 * AI アシスタント（F-029）の ChatProvider・ChatLauncher・ChatPanel は顧客向けの枠の中だけに置く。管理画面（上記の早期 return）にはチャットを出さない。
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
  const requestHeaders = await headers();
  if (requestHeaders.get(ADMIN_AREA_HEADER) === "1") {
    return (
      <html lang="ja" className={`h-full antialiased ${notoSansJP.variable}`}>
        <body className="flex min-h-full flex-col bg-bg font-body text-fg">
          <ToastProvider>{children}</ToastProvider>
        </body>
      </html>
    );
  }

  const store = await cookies();
  const hasCartCookie = store.has(CART_TOKEN_COOKIE);
  const signedIn = store.has(SESSION_COOKIE);
  const cats = await loadOrNull(getCategories(), "categories (layout)");
  // 期間限定公開の帯（公開追補 設計仕様書 6 章・DS-DEC-50）。DEMO_PUBLIC_UNTIL は実行時の
  // 環境変数なので、ここで process.env を直接読む（NEXT_PUBLIC_ にしない＝ビルド後も延長できる）。
  const demoUntilDisplay = parseDemoPublicUntil(process.env.DEMO_PUBLIC_UNTIL);

  return (
    <html lang="ja" className={`h-full antialiased ${notoSansJP.variable}`}>
      <body className="flex min-h-full flex-col bg-bg font-body text-fg">
        <ToastProvider>
          <DemoPeriodBanner untilDisplay={demoUntilDisplay} />
          <CartProvider hasCartCookie={hasCartCookie}>
            {/* AI アシスタント（P2 追補d・F-029）。商品詳細のボタンが開けるよう children を包み、右下のボタンとパネルを置く。
                管理画面は上の早期 return（x-admin-area）で通らないため、チャットは出ない */}
            <ChatProvider imageBaseUrl={getImageBaseUrl()}>
              <HeaderWithCart categories={cats?.categories ?? null} signedIn={signedIn} />
              <main id="main" className="mx-auto w-full max-w-page flex-1 px-4 py-6">
                {children}
              </main>
              <Footer />
              <ChatLauncher />
              <ChatPanel />
            </ChatProvider>
          </CartProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
