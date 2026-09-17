import type { Metadata, Viewport } from "next";
import { cookies } from "next/headers";
import { CartProvider } from "@/components/CartProvider";
import Footer from "@/components/Footer";
import HeaderWithCart from "@/components/HeaderWithCart";
import { ToastProvider } from "@/components/Toast";
import { CART_TOKEN_COOKIE } from "@/lib/cookie";
import "./globals.css";

/**
 * 共通レイアウト（設計仕様書 6.2）。ヘッダー固定＋本文＋フッター。
 * カート点数は CartProvider が `GET /api/cart` で取得し HeaderWithCart のバッジに出す（UT-WEB-01）。
 * Cookie `cart_token` が無い訪問者にはカートを作らない（取得を省いて 0 を描く）。
 * Next.js 16 では `cookies()` が Promise なので await する。
 */

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

  return (
    <html lang="ja" className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-white text-gray-900">
        <ToastProvider>
          <CartProvider hasCartCookie={hasCartCookie}>
            <HeaderWithCart />
            <main id="main" className="mx-auto w-full max-w-screen-xl flex-1 px-4 py-6">
              {children}
            </main>
            <Footer />
          </CartProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
