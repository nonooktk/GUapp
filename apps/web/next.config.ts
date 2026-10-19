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

const nextConfig: NextConfig = {
  // 設計仕様書 8.1: App Service で `node server.js` を起動するため standalone 出力にする
  output: "standalone",
  // `X-Powered-By: Next.js` を出さない（S5）
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
