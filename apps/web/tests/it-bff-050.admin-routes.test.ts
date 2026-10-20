import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { callOf, CART_TOKEN, CSRF, csrfHeaders, findSetCookie, SID_NEW, upstream } from "./helpers/bff";
import { ASID_ATTACKER, ASID_NEW, ASID_OLD } from "./helpers/admin";

// テスト設計書 IT-BFF-050〜056（管理 BFF）と ST-SEC-82・84・90 の BFF 側。設計仕様書 P2 追補c 3.1・4.0・4.5・7.3・DS-DEC-108・121・124
// FastAPI は fetch をモックして差し替える（BFF の仕事＝CSRF・本文の白リスト・Cookie・ヘッダの付け替えだけを確かめる）。

type Handler = (request: Request, ctx?: never) => Promise<Response>;
type CtxHandler = (request: Request, ctx: { params: Promise<Record<string, string>> }) => Promise<Response>;
let LOGIN: Handler;
let LOGOUT: Handler;
let CSRF_GET: Handler;
let SETTINGS: Handler;
let PRODUCT: CtxHandler;
let STOCK: CtxHandler;
let ORDER_STATUS: CtxHandler;

beforeAll(async () => {
  ({ POST: LOGIN } = await import("@/app/admin/api/auth/login/route"));
  ({ POST: LOGOUT } = await import("@/app/admin/api/auth/logout/route"));
  ({ GET: CSRF_GET } = await import("@/app/admin/api/csrf/route"));
  ({ PATCH: SETTINGS } = await import("@/app/admin/api/settings/route"));
  ({ PATCH: PRODUCT } = (await import("@/app/admin/api/products/[productId]/route")) as unknown as { PATCH: CtxHandler });
  ({ PATCH: STOCK } = (await import("@/app/admin/api/variants/[variantId]/stock/route")) as unknown as { PATCH: CtxHandler });
  ({ PATCH: ORDER_STATUS } = (await import("@/app/admin/api/orders/[orderNumber]/status/route")) as unknown as { PATCH: CtxHandler });
});

const fetchMock = vi.fn();
let warnings: string[];
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  warnings = [];
  vi.spyOn(console, "warn").mockImplementation((...a: unknown[]) => void warnings.push(a.map(String).join(" ")));
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  fetchMock.mockReset();
});

const ORDER_NO = "GU-261024-ABCDEFGH";
const BASE = "http://localhost:3000";

function call(method: string, path: string, body: unknown, headers: Record<string, string>): Request {
  return new Request(`${BASE}${path}`, {
    method,
    body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body),
    headers,
  });
}
const ctx = (params: Record<string, string>) => ({ params: Promise.resolve(params) });

/** 変更系 6 本。CSRF の検査（IT-BFF-051）に使う */
const SIX: { name: string; run: (headers: Record<string, string>) => Promise<Response> }[] = [
  { name: "login", run: (h) => LOGIN(call("POST", "/admin/api/auth/login", { login_id: "a", password: "b" }, h)) }, // pragma: allowlist secret（テスト用ダミー）
  { name: "logout", run: (h) => LOGOUT(call("POST", "/admin/api/auth/logout", undefined, h)) },
  { name: "products", run: (h) => PRODUCT(call("PATCH", "/admin/api/products/12", { published: false, expected_published: true }, h), ctx({ productId: "12" })) },
  { name: "stock", run: (h) => STOCK(call("PATCH", "/admin/api/variants/7/stock", { stock: 5, expected_stock: 0 }, h), ctx({ variantId: "7" })) },
  { name: "settings", run: (h) => SETTINGS(call("PATCH", "/admin/api/settings", { shipping_fee: 1, expected_shipping_fee: 0 }, h)) },
  { name: "order status", run: (h) => ORDER_STATUS(call("PATCH", `/admin/api/orders/${ORDER_NO}/status`, { status: "preparing" }, h), ctx({ orderNumber: ORDER_NO })) },
];

describe("IT-BFF-050 POST /admin/api/auth/login", () => {
  const body = { login_id: "demo-staff", password: "dummy-password-1" }; // pragma: allowlist secret
  const ok = { session_token: ASID_NEW, staff: { login_id: "demo-staff", role: "staff" } };

  it("本文から session_token を除き、asid(HttpOnly・SameSite=Strict・Path=/admin・Max-Age=28800)と新しい csrf_token を Set-Cookie。FastAPI へは XFF に利用者の IP(利用者送信の XFF は転送しない)", async () => {
    fetchMock.mockResolvedValue(upstream(200, ok));
    const res = await LOGIN(call("POST", "/admin/api/auth/login", body, csrfHeaders("", { "x-forwarded-for": "203.0.113.9, 10.0.0.1" })));

    expect(res.status).toBe(200);
    const text = await res.text();
    expect(text).not.toContain("session_token");
    expect(text).not.toContain(ASID_NEW);
    expect(JSON.parse(text)).toEqual({ staff: { login_id: "demo-staff", role: "staff" } });
    expect(res.headers.get("Cache-Control")).toBe("no-store");

    const asid = findSetCookie(res, "asid");
    expect(asid).toContain(`asid=${ASID_NEW}`);
    for (const attr of ["HttpOnly", "SameSite=Strict", "Path=/admin", "Max-Age=28800"]) expect(asid).toContain(attr);
    expect(asid).not.toMatch(/\bSecure\b/); // development
    const csrf = findSetCookie(res, "csrf_token");
    expect(csrf).toBeDefined();
    expect(csrf).not.toContain(`csrf_token=${CSRF};`); // 発行し直し
    expect(csrf).not.toContain("HttpOnly");
    expect(csrf).toContain("Path=/");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const c = callOf(fetchMock);
    expect(c.url).toBe("http://fastapi.test:8000/api/v1/admin/auth/login"); // gitleaks:allow（テスト用 URL）
    expect(c.init.method).toBe("POST");
    expect(c.headers.get("X-Internal-Token")).toBe("dummy-internal-token");
    expect(c.headers.get("X-Forwarded-For")).toBe("127.0.0.1");
    expect(c.headers.get("X-Admin-Session-Token")).toBeNull();
    expect(c.body).toEqual(body);
  });

  it("古い asid があれば X-Admin-Session-Token に載せる。会員の sid・cart_token は FastAPI に渡らない", async () => {
    fetchMock.mockResolvedValue(upstream(200, ok));
    await LOGIN(call("POST", "/admin/api/auth/login", body, csrfHeaders(`asid=${ASID_OLD}; sid=${SID_NEW}; cart_token=${CART_TOKEN}`)));
    const c = callOf(fetchMock);
    expect(c.headers.get("X-Admin-Session-Token")).toBe(ASID_OLD);
    expect(c.headers.get("X-Session-Token")).toBeNull();
    expect(c.headers.get("X-Cart-Token")).toBeNull();
    expect(c.headers.get("cookie")).toBeNull();
  });

  it("本文は login_id・password だけを拾う(role・session_token・next は落とす)。必須が無ければ 400", async () => {
    fetchMock.mockResolvedValue(upstream(200, ok));
    await LOGIN(call("POST", "/admin/api/auth/login", { ...body, role: "admin", session_token: "x", next: "//evil.example" }, csrfHeaders())); // pragma: allowlist secret（テスト用ダミー）
    expect(callOf(fetchMock).body).toEqual(body);

    fetchMock.mockClear();
    const res = await LOGIN(call("POST", "/admin/api/auth/login", { login_id: "a" }, csrfHeaders()));
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ code: "validation_error", fields: [{ name: "password", reason: "required" }] });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("失敗(401・403・429)は {code} をそのまま返し、Set-Cookie を出さない", async () => {
    for (const [status, code, extra] of [
      [401, "invalid_credentials", {}],
      [403, "account_locked", {}],
      [429, "rate_limited", { "Retry-After": "900" }],
    ] as const) {
      fetchMock.mockResolvedValueOnce(upstream(status, { code }, extra));
      const res = await LOGIN(call("POST", "/admin/api/auth/login", body, csrfHeaders()));
      expect(res.status).toBe(status);
      expect(await res.json()).toEqual({ code });
      expect(res.headers.getSetCookie()).toEqual([]);
      expect(res.headers.get("Cache-Control")).toBe("no-store");
      if (status === 429) expect(res.headers.get("Retry-After")).toBe("900");
    }
  });

  it("ログ(拒否ログ・エラーログ)にパスワード・トークンを書かない", async () => {
    const logs: string[] = [];
    vi.spyOn(console, "error").mockImplementation((...a: unknown[]) => void logs.push(JSON.stringify(a)));
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    await LOGIN(call("POST", "/admin/api/auth/login", body, csrfHeaders(`asid=${ASID_OLD}`)));
    fetchMock.mockResolvedValueOnce(upstream(200, { staff: {} })); // session_token 欠落
    await LOGIN(call("POST", "/admin/api/auth/login", body, csrfHeaders()));
    await LOGIN(call("POST", "/admin/api/auth/login", body, { "Content-Type": "application/json" })); // CSRF 拒否
    const all = [...logs, ...warnings].join("\n");
    expect(all.length).toBeGreaterThan(0);
    for (const secret of ["dummy-password-1", ASID_OLD, ASID_NEW, CSRF]) expect(all).not.toContain(secret);
  });
});

describe("IT-BFF-051 変更系 6 本の CSRF（ST-SEC-82）", () => {
  const cases: [string, Record<string, string>][] = [
    ["CSRF トークンなし", { "Content-Type": "application/json", cookie: `asid=${ASID_NEW}` }],
    ["ヘッダーが Cookie と不一致", { ...csrfHeaders(`asid=${ASID_NEW}`), "X-CSRF-Token": "x".repeat(43) }], // pragma: allowlist secret（テスト用ダミー）
    ["Cookie だけでヘッダーなし", { "Content-Type": "application/json", cookie: `csrf_token=${CSRF}; asid=${ASID_NEW}` }],
    ["Origin が別サイト", { ...csrfHeaders(`asid=${ASID_NEW}`), Origin: "https://evil.example" }],
    ["Sec-Fetch-Site: cross-site", { ...csrfHeaders(`asid=${ASID_NEW}`), "Sec-Fetch-Site": "cross-site" }],
    ["Origin: null", { ...csrfHeaders(`asid=${ASID_NEW}`), Origin: "null" }],
  ];

  for (const entry of SIX) {
    it.each(cases)(`${entry.name}: %s は 403 forbidden で FastAPI に届かない。拒否ログは 1 行で本文・Cookie を含まない`, async (_label, headers) => {
      const res = await entry.run(headers);
      expect(res.status).toBe(403);
      expect(await res.json()).toEqual({ code: "forbidden" });
      expect(fetchMock).not.toHaveBeenCalled();
      expect(warnings).toHaveLength(1);
      expect(warnings[0]).not.toContain(ASID_NEW);
      expect(warnings[0]).not.toContain(CSRF);
      expect(warnings[0]).not.toContain("dummy-password");
    });
  }

  it("同じ Origin・正しいトークンなら通る(6 本とも FastAPI へ届く)", async () => {
    for (const entry of SIX) {
      fetchMock.mockImplementationOnce(async () => upstream(200, { session_token: ASID_NEW }));
      const res = await entry.run({ ...csrfHeaders(`asid=${ASID_NEW}`), Origin: "http://localhost:3000" });
      expect(res.status, entry.name).not.toBe(403);
    }
    expect(fetchMock).toHaveBeenCalledTimes(SIX.length);
  });
});

describe("IT-BFF-052 POST /admin/api/auth/logout", () => {
  it.each([
    ["FastAPI が 204", () => upstream(204, null), 204],
    ["FastAPI が失敗(500)", () => upstream(500, { code: "internal_error" }), 500],
    ["FastAPI が 401(期限切れ)", () => upstream(401, { code: "unauthorized" }), 401],
  ])("%s でも asid の削除 Cookie(Max-Age=0・Path=/admin)と新しい csrf_token", async (_l, make, status) => {
    fetchMock.mockResolvedValueOnce(make());
    const res = await LOGOUT(call("POST", "/admin/api/auth/logout", undefined, csrfHeaders(`asid=${ASID_NEW}; sid=${SID_NEW}`)));
    expect(res.status).toBe(status);
    const asid = findSetCookie(res, "asid");
    expect(asid).toMatch(/^asid=;/);
    expect(asid).toContain("Max-Age=0");
    expect(asid).toContain("Path=/admin");
    expect(findSetCookie(res, "csrf_token")).not.toContain(CSRF);
    const c = callOf(fetchMock);
    expect(c.url).toBe("http://fastapi.test:8000/api/v1/admin/auth/logout"); // gitleaks:allow（テスト用 URL）
    expect(c.headers.get("X-Admin-Session-Token")).toBe(ASID_NEW);
    expect(c.headers.get("X-Session-Token")).toBeNull();
  });

  it("接続できない場合も 503 と削除 Cookie", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    const res = await LOGOUT(call("POST", "/admin/api/auth/logout", undefined, csrfHeaders(`asid=${ASID_NEW}`)));
    expect(res.status).toBe(503);
    expect(findSetCookie(res, "asid")).toContain("Max-Age=0");
    expect(findSetCookie(res, "csrf_token")).toBeDefined();
  });
});

describe("IT-BFF-053 変更系 4 本の asid", () => {
  const FOUR = SIX.filter((s) => ["products", "stock", "settings", "order status"].includes(s.name));

  for (const entry of FOUR) {
    it.each([
      ["asid なし", ""],
      ["形が違う asid(短い)", "asid=short"],
      ["形が違う asid(1 文字多い)", `asid=${ASID_NEW}x`],
      ["会員の sid だけ", `sid=${SID_NEW}`],
    ])(`${entry.name}: %s は 401 unauthorized で FastAPI を呼ばない`, async (_l, cookie) => {
      const res = await entry.run(csrfHeaders(cookie));
      expect(res.status).toBe(401);
      expect(await res.json()).toEqual({ code: "unauthorized" });
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it(`${entry.name}: 正しい形の asid は X-Admin-Session-Token に載り、X-Session-Token は載らない`, async () => {
      fetchMock.mockImplementationOnce(async () => upstream(200, { changed: true }));
      const res = await entry.run(csrfHeaders(`asid=${ASID_NEW}; sid=${SID_NEW}`));
      expect(res.status).toBe(200);
      const c = callOf(fetchMock);
      expect(c.init.method).toBe("PATCH");
      expect(c.headers.get("X-Admin-Session-Token")).toBe(ASID_NEW);
      expect(c.headers.get("X-Session-Token")).toBeNull();
      expect(c.headers.get("X-Internal-Token")).toBe("dummy-internal-token");
      expect(res.headers.get("Cache-Control")).toBe("no-store");
    });
  }

  it("取り次ぎ先のパス: 商品・在庫・設定・注文状態", async () => {
    fetchMock.mockImplementation(async () => upstream(200, {}));
    for (const entry of FOUR) await entry.run(csrfHeaders(`asid=${ASID_NEW}`));
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([
      "http://fastapi.test:8000/api/v1/admin/products/12", // gitleaks:allow（テスト用 URL）
      "http://fastapi.test:8000/api/v1/admin/variants/7/stock", // gitleaks:allow（テスト用 URL）
      "http://fastapi.test:8000/api/v1/admin/settings", // gitleaks:allow（テスト用 URL）
      `http://fastapi.test:8000/api/v1/admin/orders/${ORDER_NO}/status`, // gitleaks:allow（テスト用 URL）
    ]);
  });
});

describe("IT-BFF-054 本文の白リスト・型・大きさ（ST-SEC-90）", () => {
  const H = () => csrfHeaders(`asid=${ASID_NEW}`);

  it("余計な項目(name・role・member_id・sku・total・payment_timeout_minutes)は FastAPI に渡らない", async () => {
    fetchMock.mockImplementation(async () => upstream(200, {}));
    await PRODUCT(call("PATCH", "/admin/api/products/12", { price_incl_tax: 2000, expected_price_incl_tax: 1990, name: "x", id: 1, role: "admin", description: "d" }, H()), ctx({ productId: "12" }));
    await STOCK(call("PATCH", "/admin/api/variants/7/stock", { stock: 5, expected_stock: 0, sku: "X", variant_id: 99 }, H()), ctx({ variantId: "7" }));
    await SETTINGS(call("PATCH", "/admin/api/settings", { shipping_fee: 1, expected_shipping_fee: 0, payment_timeout_minutes: 999, foo: 1 }, H()));
    await ORDER_STATUS(call("PATCH", `/admin/api/orders/${ORDER_NO}/status`, { status: "shipped", tracking_number: "AB-1", receive_method: "store", total: 1, member_id: 5 }, H()), ctx({ orderNumber: ORDER_NO }));
    expect(callOf(fetchMock, 0).body).toEqual({ price_incl_tax: 2000, expected_price_incl_tax: 1990 });
    expect(callOf(fetchMock, 1).body).toEqual({ stock: 5, expected_stock: 0 });
    expect(callOf(fetchMock, 2).body).toEqual({ shipping_fee: 1, expected_shipping_fee: 0 });
    expect(callOf(fetchMock, 3).body).toEqual({ status: "shipped", tracking_number: "AB-1" });
  });

  it.each([
    ["在庫 stock が文字列 \"5\"", () => STOCK(call("PATCH", "/admin/api/variants/7/stock", { stock: "5", expected_stock: 0 }, H()), ctx({ variantId: "7" })), "stock"],
    ["在庫 expected_stock が欠落", () => STOCK(call("PATCH", "/admin/api/variants/7/stock", { stock: 5 }, H()), ctx({ variantId: "7" })), "expected_stock"],
    ["在庫が小数", () => STOCK(call("PATCH", "/admin/api/variants/7/stock", { stock: 1.5, expected_stock: 0 }, H()), ctx({ variantId: "7" })), "stock"],
    ["在庫が 9007199254740993(JavaScript で正確に表せない)", () => STOCK(call("PATCH", "/admin/api/variants/7/stock", '{"stock": 9007199254740993, "expected_stock": 0}', H()), ctx({ variantId: "7" })), "stock"],
    ["公開 published が文字列 \"true\"", () => PRODUCT(call("PATCH", "/admin/api/products/12", { published: "true", expected_published: true }, H()), ctx({ productId: "12" })), "published"],
    ["価格が文字列 \"1_0\"", () => PRODUCT(call("PATCH", "/admin/api/products/12", { price_incl_tax: "1_0", expected_price_incl_tax: 1 }, H()), ctx({ productId: "12" })), "price_incl_tax"],
    ["設定 tax_rate が数値", () => SETTINGS(call("PATCH", "/admin/api/settings", { tax_rate: 0.1, expected_tax_rate: "0.10" }, H())), "tax_rate"],
    ["注文状態 status が欠落", () => ORDER_STATUS(call("PATCH", `/admin/api/orders/${ORDER_NO}/status`, {}, H()), ctx({ orderNumber: ORDER_NO })), "status"],
    ["注文状態 tracking_number が数値", () => ORDER_STATUS(call("PATCH", `/admin/api/orders/${ORDER_NO}/status`, { status: "shipped", tracking_number: 123 }, H()), ctx({ orderNumber: ORDER_NO })), "tracking_number"],
  ])("%s は 400 validation_error で FastAPI を呼ばない", async (_l, run, field) => {
    const res = await run();
    expect(res.status).toBe(400);
    const json = await res.json();
    expect(json.code).toBe("validation_error");
    expect(json.fields.map((f: { name: string }) => f.name)).toContain(field);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([["[1,2]"], ['"text"'], ["not json"], ["null"], ["123"]])("本文が %s(オブジェクトでない・JSON でない)は 400", async (raw) => {
    const res = await SETTINGS(call("PATCH", "/admin/api/settings", raw, H()));
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("パスの ID が数字でない・桁が多すぎる・0 から始まる場合は 400 で FastAPI を呼ばない", async () => {
    for (const bad of ["abc", "0", "012", "1".repeat(20), "1/../2", "-1", "1.5", ""]) {
      const r1 = await PRODUCT(call("PATCH", "/admin/api/products/x", { published: true, expected_published: false }, H()), ctx({ productId: bad }));
      const r2 = await STOCK(call("PATCH", "/admin/api/variants/x/stock", { stock: 1, expected_stock: 0 }, H()), ctx({ variantId: bad }));
      expect(r1.status, bad).toBe(400);
      expect(r2.status, bad).toBe(400);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("注文番号はパスを URL エンコードして渡す(FastAPI が形で 404 にする)", async () => {
    fetchMock.mockImplementation(async () => upstream(404, { code: "not_found" }));
    const res = await ORDER_STATUS(call("PATCH", "/admin/api/orders/x/status", { status: "preparing" }, H()), ctx({ orderNumber: "../me?x=1" }));
    expect(res.status).toBe(404);
    expect(callOf(fetchMock).url).toBe("http://fastapi.test:8000/api/v1/admin/orders/..%2Fme%3Fx%3D1/status"); // gitleaks:allow（テスト用 URL）
  });

  it("9000 バイトの本文は 413 payload_too_large(Content-Length あり・なし)", async () => {
    const big = JSON.stringify({ shipping_fee: 1, pad: "x".repeat(9000) });
    const withLength = await SETTINGS(call("PATCH", "/admin/api/settings", big, { ...H(), "Content-Length": String(big.length) }));
    expect(withLength.status).toBe(413);
    expect(await withLength.json()).toEqual({ code: "payload_too_large" });
    const stream = new ReadableStream({
      start(c) {
        c.enqueue(new TextEncoder().encode(big));
        c.close();
      },
    });
    const noLength = await SETTINGS(
      new Request(`${BASE}/admin/api/settings`, { method: "PATCH", body: stream, headers: H(), duplex: "half" } as RequestInit),
    );
    expect(noLength.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("IT-BFF-055 FastAPI のエラーの透過(DS-DEC-124)", () => {
  const H = () => csrfHeaders(`asid=${ASID_NEW}`);
  const run = () => STOCK(call("PATCH", "/admin/api/variants/7/stock", { stock: 5, expected_stock: 0 }, H()), ctx({ variantId: "7" }));

  it.each([
    [401, { code: "unauthorized" }],
    [403, { code: "forbidden" }],
    [404, { code: "not_found" }],
    [409, { code: "stale_data", field: "stock", current: 3 }],
    [409, { code: "invalid_transition", from: "shipped", to: "preparing" }],
    [422, { code: "limit_exceeded", field: "stock", limit: 9999 }],
    [400, { code: "validation_error", fields: [{ name: "stock", reason: "format" }] }],
  ])("%i %j はステータスと {code} と許可した詳細キーがそのまま返る(current が落ちない)", async (status, body) => {
    fetchMock.mockImplementationOnce(async () => upstream(status, { ...body, trace: "SELECT * FROM staff", detail: "x" }));
    const res = await run();
    expect(res.status).toBe(status);
    expect(await res.json()).toEqual(body);
  });

  it("429 は Retry-After を透過する。接続不可は 503 upstream_unavailable", async () => {
    fetchMock.mockImplementationOnce(async () => upstream(429, { code: "rate_limited" }, { "Retry-After": "60" }));
    const r1 = await run();
    expect(r1.status).toBe(429);
    expect(r1.headers.get("Retry-After")).toBe("60");
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    const r2 = await run();
    expect(r2.status).toBe(503);
    expect(await r2.json()).toEqual({ code: "upstream_unavailable" });
  });
});

describe("IT-BFF-056 GET /admin/api/csrf", () => {
  it("csrf_token が未発行なら Set-Cookie で発行する(204・no-store・HttpOnly なし・Path=/)。FastAPI は呼ばない", async () => {
    const res = await CSRF_GET(call("GET", "/admin/api/csrf", undefined, {}));
    expect(res.status).toBe(204);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    const c = findSetCookie(res, "csrf_token");
    expect(c).toBeDefined();
    expect(c).not.toContain("HttpOnly");
    expect(c).toContain("Path=/");
    expect(c).toMatch(/^csrf_token=[A-Za-z0-9_-]{43};/);
    expect(await res.text()).toBe("");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("発行済み(正しい形)なら Set-Cookie を出さない。形が不正な値は発行し直す", async () => {
    const issued = await CSRF_GET(call("GET", "/admin/api/csrf", undefined, { cookie: `csrf_token=${CSRF}` }));
    expect(issued.status).toBe(204);
    expect(issued.headers.getSetCookie()).toEqual([]);
    expect(issued.headers.get("Cache-Control")).toBe("no-store");
    const broken = await CSRF_GET(call("GET", "/admin/api/csrf", undefined, { cookie: "csrf_token=bad" }));
    expect(findSetCookie(broken, "csrf_token")).toBeDefined();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("ST-SEC-84 セッション固定: 攻撃者が選んだ asid は採用されない", () => {
  it("リクエストの asid(攻撃者の値)は FastAPI に古いセッションとして渡るだけで、ブラウザへ返る asid は FastAPI が発行した値", async () => {
    const ATTACKER = ASID_ATTACKER;
    fetchMock.mockResolvedValue(upstream(200, { session_token: ASID_NEW, staff: { login_id: "demo-staff", role: "staff" } }));
    const res = await LOGIN(call("POST", "/admin/api/auth/login", { login_id: "demo-staff", password: "p" }, csrfHeaders(`asid=${ATTACKER}`))); // pragma: allowlist secret
    expect(findSetCookie(res, "asid")).toContain(`asid=${ASID_NEW}`);
    expect(res.headers.getSetCookie().join("\n")).not.toContain(ATTACKER);
    expect(callOf(fetchMock).headers.get("X-Admin-Session-Token")).toBe(ATTACKER);
  });
});

describe("IT-BFF-050（production 設定)", () => {
  it("APP_ENV=production のとき asid に Secure が付く", async () => {
    const saved = process.env.APP_ENV;
    process.env.APP_ENV = "production";
    vi.resetModules();
    try {
      const { POST } = await import("@/app/admin/api/auth/login/route");
      fetchMock.mockResolvedValue(upstream(200, { session_token: ASID_NEW, staff: { login_id: "demo-staff", role: "staff" } }));
      const res = await POST(call("POST", "/admin/api/auth/login", { login_id: "demo-staff", password: "p" }, csrfHeaders())); // pragma: allowlist secret
      const asid = findSetCookie(res, "asid")!;
      for (const attr of ["HttpOnly", "SameSite=Strict", "Path=/admin", "Max-Age=28800", "Secure"]) expect(asid).toContain(attr);
      expect(findSetCookie(res, "csrf_token")).toContain("Secure");
    } finally {
      process.env.APP_ENV = saved;
      vi.resetModules();
    }
  });
});
