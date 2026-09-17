import type { Metadata, Viewport } from "next";
import Footer from "@/components/Footer";
import Header from "@/components/Header";
import "./globals.css";

/**
 * 共通レイアウト（設計仕様書 6.2）。ヘッダー固定＋本文＋フッター。
 * カート点数は Wave 1 でカート API から取得する。Wave 0 は 0 固定。
 */

export const metadata: Metadata = {
  title: "GU EC サイト",
  description: "GU EC サイト（P1 演習）",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ja" className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-white text-gray-900">
        <Header cartCount={0} />
        <main id="main" className="mx-auto w-full max-w-screen-xl flex-1 px-4 py-6">
          {children}
        </main>
        <Footer />
      </body>
    </html>
  );
}
