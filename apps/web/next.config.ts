import type { NextConfig } from "next";

/**
 * 全パスに付けるセキュリティヘッダ（セキュリティ強化 S5）。
 * `script-src` は付けない（nonce 方式の本格 CSP は後日）。ここでは埋め込み・base 書き換え・プラグイン・フォーム送信先だけ絞る。
 */
export const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "Strict-Transport-Security", value: "max-age=31536000" },
  { key: "X-Frame-Options", value: "DENY" },
  {
    key: "Content-Security-Policy",
    value: "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'",
  },
];

/**
 * `/admin` 配下の応答に足すヘッダー（P2 追補c DS-DEC-122・126、ST-SEC-91）。全パスのヘッダーとは別の規則にして、
 * 検索エンジンに載せず、ブラウザ・中継にキャッシュさせない（管理画面は個人情報を含む）。
 */
export const ADMIN_HEADERS = [
  { key: "Cache-Control", value: "no-store" },
  { key: "X-Robots-Tag", value: "noindex, nofollow" },
];

const nextConfig: NextConfig = {
  // 設計仕様書 8.1: App Service で `node server.js` を起動するため standalone 出力にする
  output: "standalone",
  // `X-Powered-By: Next.js` を出さない（S5）
  poweredByHeader: false,
  async headers() {
    return [
      { source: "/:path*", headers: SECURITY_HEADERS },
      { source: "/admin/:path*", headers: ADMIN_HEADERS },
    ];
  },
};

export default nextConfig;
