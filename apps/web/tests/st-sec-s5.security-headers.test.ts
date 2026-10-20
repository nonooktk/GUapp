import { describe, expect, it } from "vitest";
import nextConfig from "@/next.config";

// セキュリティ強化 S5（web 側）: next.config.ts の headers() と poweredByHeader。
describe("S5 next.config のセキュリティヘッダ", () => {
  it("poweredByHeader は false（X-Powered-By を出さない）", () => {
    expect(nextConfig.poweredByHeader).toBe(false);
  });

  it("headers() は全パス（/:path*）に 6 つのヘッダを付ける（P2-c: 管理画面用の規則が 2 つ目に加わる。ST-SEC-91 は st-sec-p2c-01）", async () => {
    expect(nextConfig.headers).toBeTypeOf("function");
    const rules = await nextConfig.headers!();
    expect(rules).toHaveLength(2);
    expect(rules[0].source).toBe("/:path*");
    const map = Object.fromEntries(rules[0].headers.map((h) => [h.key, h.value]));
    expect(map).toEqual({
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "strict-origin-when-cross-origin",
      "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
      "Strict-Transport-Security": "max-age=31536000",
      "X-Frame-Options": "DENY",
      "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'",
    });
  });

  it("Content-Security-Policy に script-src は含めない（nonce 方式の本格 CSP は後日）", async () => {
    const rules = await nextConfig.headers!();
    const csp = rules[0].headers.find((h) => h.key === "Content-Security-Policy")?.value ?? "";
    expect(csp).not.toContain("script-src");
    expect(csp).not.toContain("default-src");
  });
});
