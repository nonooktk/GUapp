import { NextRequest } from "next/server";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { maskIp, sanitizePath } from "@/lib/security-log";

// セキュリティ強化 S9（web 側）: 403・413・429・400 で拒否ログを console.warn に 1 行（JSON）出す。
// 項目は event／path／method／status／code／ip の 6 つ。本文・Cookie・トークン・クエリ・個人情報は出さない。
process.env.API_BASE_URL = "http://fastapi.test:8000";
process.env.INTERNAL_TOKEN = "dummy-internal-token"; // gitleaks:allow（テスト用ダミー）
process.env.IMAGE_BASE_URL = "http://localhost:3000";
process.env.APP_ENV = "development";
process.env.SESSION_COOKIE_DOMAIN = "";
process.env.TRUSTED_PROXY_HOPS = "1";

const CSRF = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"; // gitleaks:allow // pragma: allowlist secret
const CART_TOKEN = "cartTokenAAAA_-0123456789abcdefghijklmnopq"; // gitleaks:allow // pragma: allowlist secret
const SECRET_BODY = "secret-guest@example.com"; // 本文に入れた個人情報。ログに出てはいけない // pragma: allowlist secret

const KEYS = ["code", "event", "ip", "method", "path", "status"];

let warn: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.restoreAllMocks();
});

/** console.warn がちょうど 1 回・文字列 1 引数・1 行で、JSON として読めることを確かめて中身を返す */
function onlyLog(): Record<string, unknown> {
  expect(warn).toHaveBeenCalledTimes(1);
  const args = warn.mock.calls[0];
  expect(args).toHaveLength(1);
  const line = args[0] as string;
  expect(typeof line).toBe("string");
  expect(line).not.toContain("\n");
  const parsed = JSON.parse(line) as Record<string, unknown>;
  expect(Object.keys(parsed).sort()).toEqual(KEYS);
  // 秘密・本文・Cookie・クエリは出ない
  for (const forbidden of [CSRF, CART_TOKEN, SECRET_BODY, "dummy-internal-token", "cookie", "secret=1"]) {
    expect(line).not.toContain(forbidden);
  }
  return parsed;
}

let POST: typeof import("@/app/api/cart/items/route").POST;
let LOOKUP: typeof import("@/app/api/orders/[orderNumber]/lookup/route").POST;
beforeAll(async () => {
  ({ POST } = await import("@/app/api/cart/items/route"));
  ({ POST: LOOKUP } = await import("@/app/api/orders/[orderNumber]/lookup/route"));
});

const okHeaders = { cookie: `cart_token=${CART_TOKEN}; csrf_token=${CSRF}`, "X-CSRF-Token": CSRF, "x-forwarded-for": "203.0.113.45" };

describe("S9 拒否ログ", () => {
  it("403（CSRF トークン不一致）: 1 行出る。IP は末尾 1 オクテットを 0 に丸める", async () => {
    const res = await POST(
      new Request("http://localhost:3000/api/cart/items?secret=1", {
        method: "POST",
        body: JSON.stringify({ variant_id: 1, quantity: 1, note: SECRET_BODY }),
        headers: { cookie: `cart_token=${CART_TOKEN}; csrf_token=${CSRF}`, "x-forwarded-for": "203.0.113.45" },
      }),
    );
    expect(res.status).toBe(403);
    expect(onlyLog()).toEqual({
      event: "csrf_token_rejected",
      path: "/api/cart/items",
      method: "POST",
      status: 403,
      code: "forbidden",
      ip: "203.0.113.0",
    });
  });

  it("403（別 Origin）: event は origin_rejected", async () => {
    const res = await POST(
      new Request("http://localhost:3000/api/cart/items", {
        method: "POST",
        body: "{}",
        headers: { ...okHeaders, host: "localhost:3000", origin: "https://evil.example.net" },
      }),
    );
    expect(res.status).toBe(403);
    expect(onlyLog()).toMatchObject({ event: "origin_rejected", status: 403, code: "forbidden", ip: "203.0.113.0" });
  });

  it("413: 本文の中身を出さない", async () => {
    const res = await POST(
      new Request("http://localhost:3000/api/cart/items", {
        method: "POST",
        body: JSON.stringify({ variant_id: 1, quantity: 1, note: SECRET_BODY + "x".repeat(9000) }),
        headers: okHeaders,
      }),
    );
    expect(res.status).toBe(413);
    expect(onlyLog()).toEqual({
      event: "payload_too_large",
      path: "/api/cart/items",
      method: "POST",
      status: 413,
      code: "payload_too_large",
      ip: "203.0.113.0",
    });
  });

  it("400（BFF の入力チェック）: 1 行出る", async () => {
    const res = await POST(
      new Request("http://localhost:3000/api/cart/items", {
        method: "POST",
        body: JSON.stringify({ variant_id: 1, quantity: 100 }),
        headers: okHeaders,
      }),
    );
    expect(res.status).toBe(400);
    expect(onlyLog()).toMatchObject({ event: "validation_rejected", status: 400, code: "validation_error" });
  });

  it("注文番号を含むパスは番号を伏せる", async () => {
    const res = await LOOKUP(
      new Request("http://localhost:3000/api/orders/GU-261019-ABCD2345/lookup", {
        method: "POST",
        body: JSON.stringify({ guest_email: SECRET_BODY }),
        headers: { cookie: `csrf_token=${CSRF}` },
      }),
      { params: Promise.resolve({ orderNumber: "GU-261019-ABCD2345" }) },
    );
    expect(res.status).toBe(403);
    const log = onlyLog();
    expect(log.path).toBe("/api/orders/:order_number/lookup");
  });

  it("429（proxy）: 1 行出る。ヘッダやクエリは出さない", async () => {
    vi.resetModules();
    process.env.RATE_LIMIT_API_PER_MIN = "1";
    const { proxy } = await import("@/proxy");
    const mk = () =>
      new NextRequest("http://localhost:3000/api/products?q=secret=1", {
        headers: { "x-forwarded-for": "198.51.100.77", authorization: "Basic c2VjcmV0", cookie: `csrf_token=${CSRF}` },
      });
    expect(proxy(mk()).status).not.toBe(429);
    expect(warn).not.toHaveBeenCalled(); // 通した分は拒否ログではない
    expect(proxy(mk()).status).toBe(429);
    expect(onlyLog()).toEqual({
      event: "rate_limited",
      path: "/api/products",
      method: "GET",
      status: 429,
      code: "rate_limited",
      ip: "198.51.100.0",
    });
    delete process.env.RATE_LIMIT_API_PER_MIN;
  });
});

describe("S9 maskIp / sanitizePath", () => {
  it.each([
    ["203.0.113.45", "203.0.113.0"],
    ["127.0.0.1", "127.0.0.0"],
    ["2001:db8:abcd:12:3456:789a:bcde:f012", "2001:db8:abcd:0:0:0:0:0"],
    ["2001:DB8::1", "2001:db8:0:0:0:0:0:0"],
    ["::1", "0:0:0:0:0:0:0:0"],
    ["::ffff:203.0.113.45", "203.0.113.0"],
    ["fe80::", "fe80:0:0:0:0:0:0:0"],
    ["unknown", "unknown"],
    ["", "unknown"],
    ["1:2:3:4:5:6:7:8:9", "unknown"],
  ])("maskIp(%s) = %s", (input, expected) => {
    expect(maskIp(input)).toBe(expected);
  });

  it("sanitizePath: クエリを落とし、注文番号を伏せ、200 文字に切る", () => {
    expect(sanitizePath("/api/search?q=abc")).toBe("/api/search");
    expect(sanitizePath("/orders/GU-261019-ABCD2345")).toBe("/orders/:order_number");
    expect(sanitizePath("/" + "a".repeat(500))).toHaveLength(200);
  });
});
