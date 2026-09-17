import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 設計仕様書 8.1: App Service で `node server.js` を起動するため standalone 出力にする
  output: "standalone",
};

export default nextConfig;
