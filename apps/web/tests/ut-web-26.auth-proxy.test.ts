import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { callOf, csrfHeaders, findSetCookie, jsonPost, SID_NEW, SID_OLD, upstream } from "./helpers/bff";

// テスト設計書 UT-WEB-26（認証 BFF の共通処理 auth-proxy）。設計仕様書 4.0・4.7・DS-DEC-60・72

type Mod = typeof import("@/lib/server/auth-proxy");
let mod: Mod;
const fetchMock = vi.fn();

beforeEach(async () => {
  mod = await import("@/lib/server/auth-proxy");
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

const req = (cookie = "") => jsonPost("/api/auth/x", {}, csrfHeaders(cookie));

describe("UT-WEB-26 auth-proxy", () => {
  it("stripSessionSecrets: 最上位の session_token・cart_token を除く。オブジェクト以外はそのまま", () => {
    expect(mod.stripSessionSecrets({ a: 1, session_token: "s", cart_token: "c", member: { session_token: "keep" } })).toEqual({
      a: 1,
      member: { session_token: "keep" },
    });
    expect(mod.stripSessionSecrets(null)).toBeNull();
    expect(mod.stripSessionSecrets([1])).toEqual([1]);
    expect(mod.stripSessionSecrets("x")).toBe("x");
  });

  it("login: session_token を本文から除いて sid の Set-Cookie にする。csrf_token は発行し直す", async () => {
    fetchMock.mockResolvedValue(upstream(200, { session_token: SID_NEW, member: { name: "n", email_verified: false } }));
    const res = await mod.proxyAuthRequest(req(), "/auth/login", { json: {}, mode: "login" });
    expect(await res.json()).toEqual({ member: { name: "n", email_verified: false } });
    expect(findSetCookie(res, "sid")).toContain(`sid=${SID_NEW}`);
    expect(findSetCookie(res, "csrf_token")).toBeDefined();
  });

  it("plain: Set-Cookie を出さない（csrf_token も発行し直さない）", async () => {
    fetchMock.mockResolvedValue(upstream(202, { status: "accepted" }));
    const res = await mod.proxyAuthRequest(req(), "/auth/register", { json: {} });
    expect(res.status).toBe(202);
    expect(res.headers.getSetCookie()).toEqual([]);
  });

  it("plain は sid があっても X-Session-Token を付けない。forwardSession のときだけ付ける", async () => {
    fetchMock.mockResolvedValue(upstream(200, { status: "x" }));
    await mod.proxyAuthRequest(req(`sid=${SID_OLD}`), "/auth/register", { json: {} });
    expect(callOf(fetchMock, 0).headers.get("X-Session-Token")).toBeNull();
    await mod.proxyAuthRequest(req(`sid=${SID_OLD}`), "/restock-notifications", { json: {}, forwardSession: true });
    expect(callOf(fetchMock, 1).headers.get("X-Session-Token")).toBe(SID_OLD);
  });

  it("429 の Retry-After は数字のときだけ透過する（HTTP 日付・記号入りは落とす）", async () => {
    for (const [value, expected] of [["900", "900"], ["Wed, 21 Oct 2026 07:28:00 GMT", null], ["12 3", null], ["", null]] as const) {
      fetchMock.mockResolvedValueOnce(upstream(429, { code: "rate_limited" }, value ? { "Retry-After": value } : {}));
      const res = await mod.proxyAuthRequest(req(), "/auth/login", { json: {}, mode: "login" });
      expect(res.status).toBe(429);
      expect(res.headers.get("Retry-After")).toBe(expected);
    }
  });

  it("接続不可は 503 upstream_unavailable。予期しない例外は 500（本文に例外のメッセージを出さない）", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    const down = await mod.proxyAuthRequest(req(), "/auth/login", { json: {}, mode: "login" });
    expect(down.status).toBe(503);
    expect(await down.json()).toEqual({ code: "upstream_unavailable" });
  });

  it("logout: 成功でも失敗でも sid の削除 Cookie と新しい csrf_token", async () => {
    fetchMock.mockResolvedValueOnce(upstream(204, null));
    const ok = await mod.proxyAuthRequest(req(`sid=${SID_OLD}`), "/auth/logout", { mode: "logout" });
    expect(ok.status).toBe(204);
    expect(findSetCookie(ok, "sid")).toContain("Max-Age=0");
    expect(findSetCookie(ok, "csrf_token")).toBeDefined();

    fetchMock.mockResolvedValueOnce(upstream(401, { code: "unauthorized" }));
    const ng = await mod.proxyAuthRequest(req(`sid=${SID_OLD}`), "/auth/logout", { mode: "logout" });
    expect(ng.status).toBe(401);
    expect(findSetCookie(ng, "sid")).toContain("Max-Age=0");
  });

  it("pickBody: 必須は文字列のみ、任意は型が合うものだけ。それ以外のキーは落とす", () => {
    const r = mod.pickBody(
      { a: "x", b: 1, c: "y", d: true, e: "no", extra: "z" },
      { required: ["a", "b"], optionalStrings: ["c", "e"], optionalBooleans: ["d", "missing"] },
    );
    expect(r.payload).toEqual({ a: "x", c: "y", e: "no", d: true });
    expect(r.fields).toEqual([{ name: "b", reason: "required" }]);
    expect(mod.pickBody({ c: 5 }, { required: [], optionalStrings: ["c"] }).fields).toEqual([{ name: "c", reason: "format" }]);
  });
});
