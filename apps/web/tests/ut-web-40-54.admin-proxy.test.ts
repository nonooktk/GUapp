import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CART_TOKEN, callOf, csrfHeaders, SID_NEW, upstream } from "./helpers/bff";
import { ASID_NEW, ASID_OLD } from "./helpers/admin";
import { pickAdminBody, proxyAdminRequest } from "@/lib/server/admin-proxy";
import { sanitizeErrorBody } from "@/lib/server/api";

// テスト設計書 UT-WEB-50（管理 BFF の共通処理 admin-proxy）。設計仕様書 P2 追補c 4.5

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  fetchMock.mockReset();
});

function req(cookie = "", extra: Record<string, string> = {}): Request {
  return new Request("http://localhost:3000/admin/api/x", {
    method: "PATCH",
    headers: { ...csrfHeaders(cookie, extra) },
    body: "{}",
  });
}

describe("UT-WEB-50 proxyAdminRequest", () => {
  it("asid の値だけを X-Admin-Session-Token に載せる。会員の sid・cart_token は FastAPI に渡さない", async () => {
    fetchMock.mockResolvedValue(upstream(200, { ok: true }));
    const res = await proxyAdminRequest(req(`asid=${ASID_NEW}; sid=${SID_NEW}; cart_token=${CART_TOKEN}`), "/admin/settings", {
      mode: "update",
      json: { shipping_fee: 1 },
    });
    expect(res.status).toBe(200);
    const c = callOf(fetchMock);
    expect(c.url).toBe("http://fastapi.test:8000/api/v1/admin/settings"); // gitleaks:allow（テスト用 URL）
    expect(c.init.method).toBe("PATCH");
    expect(c.headers.get("X-Admin-Session-Token")).toBe(ASID_NEW);
    expect(c.headers.get("X-Session-Token")).toBeNull();
    expect(c.headers.get("X-Cart-Token")).toBeNull();
    expect(c.headers.get("X-Internal-Token")).toBe("dummy-internal-token");
    expect(c.headers.get("X-Forwarded-For")).toBe("127.0.0.1");
    expect(c.headers.get("cookie")).toBeNull();
    expect(c.body).toEqual({ shipping_fee: 1 });
  });

  it("更新系: asid が無い・形が違うときは FastAPI を呼ばずに 401 unauthorized(no-store)", async () => {
    for (const cookie of ["", "asid=short", `asid=${ASID_NEW}x`, `sid=${SID_NEW}`]) {
      const res = await proxyAdminRequest(req(cookie), "/admin/settings", { mode: "update" });
      expect(res.status).toBe(401);
      expect(await res.json()).toEqual({ code: "unauthorized" });
      expect(res.headers.get("Cache-Control")).toBe("no-store");
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("login: 応答の session_token を本文から除き asid の Set-Cookie にする。csrf_token を発行し直す。古い asid は X-Admin-Session-Token に載せる", async () => {
    fetchMock.mockResolvedValue(upstream(200, { session_token: ASID_NEW, staff: { login_id: "demo-staff", role: "staff" } }));
    const res = await proxyAdminRequest(req(`asid=${ASID_OLD}`), "/admin/auth/login", { mode: "login", method: "POST", json: { login_id: "a", password: "b" } }); // pragma: allowlist secret（テスト用ダミー）
    const text = await res.text();
    expect(text).not.toContain(ASID_NEW);
    expect(text).not.toContain("session_token");
    expect(JSON.parse(text)).toEqual({ staff: { login_id: "demo-staff", role: "staff" } });
    const cookies = res.headers.getSetCookie();
    expect(cookies.find((c) => c.startsWith(`asid=${ASID_NEW}`))).toContain("Path=/admin");
    expect(cookies.some((c) => c.startsWith("csrf_token="))).toBe(true);
    expect(callOf(fetchMock).headers.get("X-Admin-Session-Token")).toBe(ASID_OLD);
    expect(callOf(fetchMock).init.method).toBe("POST");
  });

  it("login: 契約違反(session_token が無い・形が違う)は 502 で Cookie を発行しない", async () => {
    fetchMock.mockResolvedValueOnce(upstream(200, { staff: {} }));
    const r1 = await proxyAdminRequest(req(), "/admin/auth/login", { mode: "login", method: "POST" });
    expect(r1.status).toBe(502);
    expect(r1.headers.getSetCookie()).toEqual([]);
    fetchMock.mockResolvedValueOnce(upstream(200, { session_token: "short" })); // pragma: allowlist secret（テスト用ダミー）
    const r2 = await proxyAdminRequest(req(), "/admin/auth/login", { mode: "login", method: "POST" });
    expect(r2.status).toBe(502);
    expect(r2.headers.getSetCookie()).toEqual([]);
  });

  it("login 失敗(401)は Set-Cookie を出さない。Retry-After は数字のときだけ透過する(429)", async () => {
    fetchMock.mockResolvedValueOnce(upstream(401, { code: "invalid_credentials" }));
    const r1 = await proxyAdminRequest(req(), "/admin/auth/login", { mode: "login", method: "POST" });
    expect(r1.status).toBe(401);
    expect(r1.headers.getSetCookie()).toEqual([]);
    expect(await r1.json()).toEqual({ code: "invalid_credentials" });

    fetchMock.mockResolvedValueOnce(upstream(429, { code: "rate_limited" }, { "Retry-After": "900" }));
    const r2 = await proxyAdminRequest(req(), "/admin/auth/login", { mode: "login", method: "POST" });
    expect(r2.status).toBe(429);
    expect(r2.headers.get("Retry-After")).toBe("900");

    fetchMock.mockResolvedValueOnce(upstream(429, { code: "rate_limited" }, { "Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT" }));
    const r3 = await proxyAdminRequest(req(), "/admin/auth/login", { mode: "login", method: "POST" });
    expect(r3.headers.get("Retry-After")).toBeNull();
  });

  it("接続不可は 503 upstream_unavailable。予期しない例外は 500 で本文・トークンをログに書かない", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    const r1 = await proxyAdminRequest(req(`asid=${ASID_NEW}`), "/admin/settings", { mode: "update", json: { shipping_fee: 1 } });
    expect(r1.status).toBe(503);
    expect(await r1.json()).toEqual({ code: "upstream_unavailable" });

    const logs: string[] = [];
    vi.spyOn(console, "error").mockImplementation((...a: unknown[]) => void logs.push(JSON.stringify(a)));
    // 本文の読み取りで予期しない例外（fetch 自体の失敗は 503 になる）
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers(),
      text: async () => {
        throw new RangeError("boom");
      },
    });
    const r2 = await proxyAdminRequest(req(`asid=${ASID_NEW}`), "/admin/settings", { mode: "update", json: { shipping_fee: 4321 } });
    expect(r2.status).toBe(500);
    const all = logs.join("\n");
    expect(all).not.toContain(ASID_NEW);
    expect(all).not.toContain("4321");
  });

  it("許可した詳細キー(current を含む)だけを返す。許可外のキーは落とす", async () => {
    fetchMock.mockResolvedValue(upstream(409, { code: "stale_data", field: "stock", current: 3, stack: "x", sql: "SELECT 1" }));
    const res = await proxyAdminRequest(req(`asid=${ASID_NEW}`), "/admin/variants/7/stock", { mode: "update" });
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ code: "stale_data", field: "stock", current: 3 });
    expect(sanitizeErrorBody(409, { code: "stale_data", current: "0.08" })).toEqual({ code: "stale_data", current: "0.08" });
  });

  it("logout: asid あり→ FastAPI 204 でも失敗でも接続不可でも asid の削除 Cookie と新しい csrf_token。asid なしは FastAPI を呼ばず 204", async () => {
    fetchMock.mockResolvedValueOnce(upstream(204, null));
    const ok = await proxyAdminRequest(req(`asid=${ASID_NEW}`), "/admin/auth/logout", { mode: "logout", method: "POST" });
    expect(ok.status).toBe(204);
    expect(callOf(fetchMock).headers.get("X-Admin-Session-Token")).toBe(ASID_NEW);

    fetchMock.mockResolvedValueOnce(upstream(500, { code: "internal_error" }));
    const failed = await proxyAdminRequest(req(`asid=${ASID_NEW}`), "/admin/auth/logout", { mode: "logout", method: "POST" });
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    const down = await proxyAdminRequest(req(`asid=${ASID_NEW}`), "/admin/auth/logout", { mode: "logout", method: "POST" });
    const none = await proxyAdminRequest(req(), "/admin/auth/logout", { mode: "logout", method: "POST" });
    expect(failed.status).toBe(500);
    expect(down.status).toBe(503);
    expect(none.status).toBe(204);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    for (const r of [ok, failed, down, none]) {
      const cookies = r.headers.getSetCookie();
      expect(cookies.find((c) => c.startsWith("asid=;"))).toContain("Max-Age=0");
      expect(cookies.find((c) => c.startsWith("asid=;"))).toContain("Path=/admin");
      expect(cookies.some((c) => c.startsWith("csrf_token="))).toBe(true);
      expect(r.headers.get("Cache-Control")).toBe("no-store");
    }
  });
});

describe("pickAdminBody（白リストと型検査）", () => {
  const spec = { fields: { stock: "int", expected_stock: "int", published: "boolean", note: "string" }, required: ["stock"] } as const;

  it("白リスト外のキーは落とす。null・未指定の任意項目は落とす", () => {
    const r = pickAdminBody({ stock: 5, expected_stock: 0, name: "x", role: "admin", member_id: 1, note: null }, spec);
    expect(r.fields).toEqual([]);
    expect(r.payload).toEqual({ stock: 5, expected_stock: 0 });
  });

  it("型違いは format、必須の欠落・null は required", () => {
    expect(pickAdminBody({ stock: "5" }, spec).fields).toEqual([{ name: "stock", reason: "format" }]);
    expect(pickAdminBody({ stock: 5.5 }, spec).fields).toEqual([{ name: "stock", reason: "format" }]);
    expect(pickAdminBody({ stock: true }, spec).fields).toEqual([{ name: "stock", reason: "format" }]);
    expect(pickAdminBody({ stock: Number.NaN }, spec).fields).toEqual([{ name: "stock", reason: "format" }]);
    expect(pickAdminBody({ stock: 9007199254740993 }, spec).fields).toEqual([{ name: "stock", reason: "format" }]);
    expect(pickAdminBody({}, spec).fields).toEqual([{ name: "stock", reason: "required" }]);
    expect(pickAdminBody({ stock: null }, spec).fields).toEqual([{ name: "stock", reason: "required" }]);
    expect(pickAdminBody({ stock: 1, published: "true" }, spec).fields).toEqual([{ name: "published", reason: "format" }]);
  });

  it("false・0・空文字は値として拾う(落とさない)", () => {
    const r = pickAdminBody({ stock: 0, published: false, note: "" }, spec);
    expect(r.payload).toEqual({ stock: 0, published: false, note: "" });
  });
});
