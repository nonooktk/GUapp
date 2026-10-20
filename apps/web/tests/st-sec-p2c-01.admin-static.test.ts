import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import nextConfig, { ADMIN_HEADERS, SECURITY_HEADERS } from "@/next.config";

// ST-SEC-91（管理画面の応答ヘッダー・公開サイトに管理画面へのリンクがない）・ST-SEC-87（画面の XSS 対策）のうち、
// ソースと設定から機械的に確かめられる部分。設計仕様書 P2 追補c 7.1・8.2・DS-DEC-122

const ROOT = path.resolve(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === ".next") continue;
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.(ts|tsx)$/.test(name)) out.push(full);
  }
  return out;
}
const rel = (f: string) => path.relative(ROOT, f);
/** コメントを除いたコード(説明文に /admin や dangerouslySetInnerHTML と書いてあっても数えない) */
const code = (f: string) =>
  readFileSync(f, "utf-8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/(?<=\s)\/\/\s.*$/gm, "");

describe("ST-SEC-91 /admin 配下の応答ヘッダー(next.config.ts)", () => {
  it("/admin/:path* に Cache-Control: no-store と X-Robots-Tag: noindex, nofollow を付ける。全パスのヘッダーはそのまま", async () => {
    const rules = await nextConfig.headers!();
    const admin = rules.find((r) => r.source === "/admin/:path*");
    expect(admin).toBeDefined();
    expect(Object.fromEntries(admin!.headers.map((h) => [h.key, h.value]))).toEqual({
      "Cache-Control": "no-store",
      "X-Robots-Tag": "noindex, nofollow",
    });
    expect(ADMIN_HEADERS).toHaveLength(2);
    // 全パスの規則(セキュリティヘッダー 6 つ)は先頭に残り、/admin にも適用される
    expect(rules[0].source).toBe("/:path*");
    expect(rules[0].headers).toEqual(SECURITY_HEADERS);
    expect(SECURITY_HEADERS.map((h) => h.key)).toEqual(
      expect.arrayContaining(["X-Frame-Options", "Content-Security-Policy", "Strict-Transport-Security", "X-Content-Type-Options"]),
    );
  });
});

describe("ST-SEC-91 公開サイトのソースに管理画面へのリンクがない", () => {
  const publicFiles = [
    ...walk(path.join(ROOT, "app")).filter((f) => !rel(f).startsWith(path.join("app", "admin"))),
    ...walk(path.join(ROOT, "components")).filter((f) => !rel(f).startsWith(path.join("components", "admin"))),
  ];

  it("app/（admin 以外）と components/（admin 以外）に /admin への href・push・redirect がない", () => {
    expect(publicFiles.length).toBeGreaterThan(20);
    const offenders = publicFiles.filter((f) => /["'`]\/admin(?:["'`/?#]|$)/.test(code(f)));
    expect(offenders.map(rel)).toEqual([]);
  });

  it("管理画面のページ・部品が、公開サイトのパス(/ ・/login・/mypage・/cart・/products)へのリンクを持たない", () => {
    const files = [...walk(path.join(ROOT, "app", "admin")), ...walk(path.join(ROOT, "components", "admin"))].filter((f) => !f.includes(`${path.sep}api${path.sep}`));
    const offenders = files.filter((f) => /href=["'{`]\s*["'`]?\/(?:login|mypage|cart|products|register|search)?["'`]/.test(readFileSync(f, "utf-8").replace(/\/admin\/[a-z/]*/g, "")));
    expect(offenders.map(rel)).toEqual([]);
  });
});

describe("ST-SEC-87 画面は React の既定のエスケープだけを使う", () => {
  it("管理画面のコードに dangerouslySetInnerHTML・innerHTML・eval がない", () => {
    const files = [
      ...walk(path.join(ROOT, "app", "admin")),
      ...walk(path.join(ROOT, "components", "admin")),
      ...walk(path.join(ROOT, "lib")).filter((f) => /admin/.test(f)),
    ];
    expect(files.length).toBeGreaterThan(20);
    const offenders = files.filter((f) => /dangerouslySetInnerHTML|\.innerHTML|\beval\(|new Function\(/.test(code(f)));
    expect(offenders.map(rel)).toEqual([]);
  });
});

describe("管理画面のコードが秘密・個人情報を扱わない", () => {
  it("Route Handler（/admin/api）と取り次ぎは console.log を使わず、console.error/warn に本文・パスワード・トークンを渡さない", () => {
    const files = [...walk(path.join(ROOT, "app", "admin", "api")), path.join(ROOT, "lib", "server", "admin-proxy.ts"), path.join(ROOT, "lib", "server", "admin.ts")];
    for (const f of files) {
      const src = code(f);
      expect(src, rel(f)).not.toMatch(/console\.log\(/);
      for (const m of src.matchAll(/console\.(?:error|warn|info)\(([\s\S]*?)\);/g)) {
        expect(m[1].replace(/"[^"]*"/g, '""'), rel(f)).not.toMatch(/password|session_token|asid|token|\.json\(|request\.body|\bbody\b|email/i);
      }
    }
  });

  it("会員の Cookie・ヘッダー(sid・X-Session-Token・cart_token)を管理系のコードが参照しない", () => {
    const files = [
      path.join(ROOT, "lib", "admin-cookie.ts"),
      path.join(ROOT, "lib", "server", "admin-proxy.ts"),
      path.join(ROOT, "lib", "server", "admin.ts"),
      ...walk(path.join(ROOT, "app", "admin", "api")),
    ];
    for (const f of files) {
      expect(code(f), rel(f)).not.toMatch(/(?<![A-Z_])SESSION_COOKIE(?![A-Z_])|(?<![A-Z_])SESSION_TOKEN_HEADER|CART_TOKEN|readSessionToken|"sid"|(?<!Admin-)Session-Token|X-Cart-Token/);
    }
  });
});
