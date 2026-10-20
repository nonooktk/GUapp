import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { callOf, CSRF, csrfHeaders, findSetCookie, jsonPost, SID_NEW, SID_OLD, upstream } from "./helpers/bff";

// テスト設計書 IT-BFF-030a〜f・IT-BFF-031（認証系 BFF）。設計仕様書 3.1・4.0・4.1・4.7・7.3・DS-DEC-72・85。
// FastAPI は fetch をモックして差し替える（BFF の仕事＝CSRF・本文の白リスト・Cookie・ヘッダの付け替えだけを確かめる）。

type Handler = (request: Request) => Promise<Response>;
let LOGIN: Handler;
let LOGOUT: Handler;
let REGISTER: Handler;
let VERIFY: Handler;
let RESET_REQ: Handler;
let RESET_CONFIRM: Handler;

beforeAll(async () => {
  ({ POST: LOGIN } = await import("@/app/api/auth/login/route"));
  ({ POST: LOGOUT } = await import("@/app/api/auth/logout/route"));
  ({ POST: REGISTER } = await import("@/app/api/auth/register/route"));
  ({ POST: VERIFY } = await import("@/app/api/auth/verify-email/route"));
  ({ POST: RESET_REQ } = await import("@/app/api/auth/password-reset/request/route"));
  ({ POST: RESET_CONFIRM } = await import("@/app/api/auth/password-reset/confirm/route"));
});

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

const loginBody = { email: "demo-member1@example.com", password: "dummy-password-1" }; // pragma: allowlist secret
const loginOk = { session_token: SID_NEW, member: { name: "デモ 一郎", email_verified: true } };

describe("IT-BFF-030a POST /api/auth/login 成功", () => {
  it("本文から session_token を除き、sid（HttpOnly・SameSite=Lax・Path=/・Max-Age=86400）と新しい csrf_token を Set-Cookie し、FastAPI へは XFF に利用者の IP（利用者送信の XFF は転送しない）", async () => {
    fetchMock.mockResolvedValue(upstream(200, loginOk));
    const res = await LOGIN(jsonPost("/api/auth/login", loginBody, csrfHeaders("", { "x-forwarded-for": "203.0.113.9, 10.0.0.1" })));

    expect(res.status).toBe(200);
    const text = await res.text();
    expect(text).not.toContain("session_token");
    expect(text).not.toContain(SID_NEW);
    expect(JSON.parse(text)).toEqual({ member: { name: "デモ 一郎", email_verified: true } });
    expect(res.headers.get("Cache-Control")).toBe("no-store");

    const sid = findSetCookie(res, "sid");
    expect(sid).toBeDefined();
    expect(sid).toContain(`sid=${SID_NEW}`);
    for (const attr of ["HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=86400"]) expect(sid).toContain(attr);
    expect(sid).not.toMatch(/\bSecure\b/); // development
    const csrf = findSetCookie(res, "csrf_token");
    expect(csrf).toBeDefined();
    expect(csrf).not.toContain(`csrf_token=${CSRF};`); // 発行し直し

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const c = callOf(fetchMock);
    expect(c.url).toBe("http://fastapi.test:8000/api/v1/auth/login"); // gitleaks:allow（テスト用 URL）
    expect(c.init.method).toBe("POST");
    expect(c.headers.get("X-Internal-Token")).toBe("dummy-internal-token");
    expect(c.headers.get("X-Forwarded-For")).toBe("127.0.0.1");
    expect(c.headers.get("X-Session-Token")).toBeNull();
    expect(c.body).toEqual(loginBody);
  });

  it("古い sid が Cookie にあれば X-Session-Token に載せて渡す（FastAPI が古い行を削除して再発行する。ST-SEC-43）", async () => {
    fetchMock.mockResolvedValue(upstream(200, loginOk));
    const res = await LOGIN(jsonPost("/api/auth/login", loginBody, csrfHeaders(`sid=${SID_OLD}`)));
    expect(res.status).toBe(200);
    expect(callOf(fetchMock).headers.get("X-Session-Token")).toBe(SID_OLD);
    // 発行される sid は FastAPI が返した新しい値だけ（古い値・利用者が選んだ値は採用しない）
    expect(findSetCookie(res, "sid")).toContain(`sid=${SID_NEW}`);
  });

  it("形が違う sid（43 文字でない・記号入り）は X-Session-Token に載せない", async () => {
    fetchMock.mockResolvedValue(upstream(200, loginOk));
    await LOGIN(jsonPost("/api/auth/login", loginBody, csrfHeaders("sid=short")));
    expect(callOf(fetchMock).headers.get("X-Session-Token")).toBeNull();
  });

  it("FastAPI が session_token を返さない（契約違反）なら 502 で Cookie を発行しない", async () => {
    fetchMock.mockResolvedValue(upstream(200, { member: { name: "x", email_verified: true } }));
    const res = await LOGIN(jsonPost("/api/auth/login", loginBody, csrfHeaders()));
    expect(res.status).toBe(502);
    expect(findSetCookie(res, "sid")).toBeUndefined();
  });
});

describe("IT-BFF-030a（production 設定）sid に Secure が付く", () => {
  it("APP_ENV=production のとき sid は Secure", async () => {
    vi.resetModules();
    const prev = process.env.APP_ENV;
    process.env.APP_ENV = "production";
    try {
      const { POST } = await import("@/app/api/auth/login/route");
      fetchMock.mockResolvedValue(upstream(200, loginOk));
      const res = await POST(jsonPost("/api/auth/login", loginBody, csrfHeaders()));
      const sid = findSetCookie(res, "sid");
      expect(sid).toMatch(/\bSecure\b/);
      expect(sid).toContain("HttpOnly");
      expect(findSetCookie(res, "csrf_token")).toMatch(/\bSecure\b/);
    } finally {
      process.env.APP_ENV = prev;
      vi.resetModules();
    }
  });
});

describe("IT-BFF-030b CSRF（認証系 6 本）", () => {
  const routes: [string, () => Handler, unknown][] = [
    ["/api/auth/login", () => LOGIN, loginBody],
    ["/api/auth/logout", () => LOGOUT, undefined],
    ["/api/auth/register", () => REGISTER, { email: "a@example.com", password: "dummy-password-1", name: "テスト" }], // pragma: allowlist secret
    ["/api/auth/verify-email", () => VERIFY, { token: SID_NEW }],
    ["/api/auth/password-reset/request", () => RESET_REQ, { email: "a@example.com" }],
    ["/api/auth/password-reset/confirm", () => RESET_CONFIRM, { token: SID_NEW, password: "dummy-password-2" }], // pragma: allowlist secret
  ];

  for (const [path, handler, body] of routes) {
    it(`${path}: CSRF トークンなし／不一致／Origin 不一致はすべて 403 forbidden で FastAPI を呼ばない`, async () => {
      const cases: Record<string, Record<string, string>> = {
        "トークンなし": { cookie: `csrf_token=${CSRF}`, "Content-Type": "application/json" },
        "Cookie なし": { "X-CSRF-Token": CSRF, "Content-Type": "application/json" },
        "不一致": { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": CSRF.replace(/.$/, "Z"), "Content-Type": "application/json" },
        "Origin 不一致": csrfHeaders("", { origin: "https://evil.example" }),
      };
      for (const [label, headers] of Object.entries(cases)) {
        const res = await handler()(jsonPost(path, body ?? "", headers));
        expect(res.status, `${path} ${label}`).toBe(403);
        expect(await res.json()).toEqual({ code: "forbidden" });
      }
      expect(fetchMock).not.toHaveBeenCalled();
    });
  }

  it("ログアウトの GET の窓口は無い（route が GET を export しない＝405。ST-SEC-46）", async () => {
    const mod = (await import("@/app/api/auth/logout/route")) as Record<string, unknown>;
    expect(mod.GET).toBeUndefined();
    expect(typeof mod.POST).toBe("function");
  });
});

describe("IT-BFF-030c POST /api/auth/logout", () => {
  it("成功（204）: X-Session-Token に sid が載り、sid の削除 Cookie（Max-Age=0）と新しい csrf_token を返す", async () => {
    fetchMock.mockResolvedValue(upstream(204, null));
    const res = await LOGOUT(jsonPost("/api/auth/logout", "", csrfHeaders(`sid=${SID_OLD}`)));
    expect(res.status).toBe(204);
    expect(await res.text()).toBe("");
    const c = callOf(fetchMock);
    expect(c.url).toBe("http://fastapi.test:8000/api/v1/auth/logout"); // gitleaks:allow（テスト用 URL）
    expect(c.headers.get("X-Session-Token")).toBe(SID_OLD);

    const sid = findSetCookie(res, "sid");
    expect(sid).toMatch(/^sid=;/);
    expect(sid).toContain("Max-Age=0");
    expect(sid).toContain("HttpOnly");
    const csrf = findSetCookie(res, "csrf_token");
    expect(csrf).toBeDefined();
    expect(csrf).not.toContain(`csrf_token=${CSRF};`);
  });

  it("FastAPI が失敗（500）・接続不可でも sid の削除 Cookie と新しい csrf_token を返す", async () => {
    fetchMock.mockResolvedValueOnce(upstream(500, { code: "internal_error", message: "処理中にエラーが発生しました" }));
    const failed = await LOGOUT(jsonPost("/api/auth/logout", "", csrfHeaders(`sid=${SID_OLD}`)));
    expect(failed.status).toBe(500);
    expect(findSetCookie(failed, "sid")).toContain("Max-Age=0");
    expect(findSetCookie(failed, "csrf_token")).toBeDefined();

    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    const down = await LOGOUT(jsonPost("/api/auth/logout", "", csrfHeaders(`sid=${SID_OLD}`)));
    expect(down.status).toBe(503);
    expect(await down.json()).toEqual({ code: "upstream_unavailable" });
    expect(findSetCookie(down, "sid")).toContain("Max-Age=0");
  });

  it("sid が無くても FastAPI を呼んで 204 を返す（冪等）", async () => {
    fetchMock.mockResolvedValue(upstream(204, null));
    const res = await LOGOUT(jsonPost("/api/auth/logout", "", csrfHeaders()));
    expect(res.status).toBe(204);
    expect(callOf(fetchMock).headers.get("X-Session-Token")).toBeNull();
  });
});

describe("IT-BFF-030d ログイン失敗の透過", () => {
  it("401 invalid_credentials・403 account_locked・429（Retry-After: 900）・422 がステータスと {code} のまま透過され、Set-Cookie に sid が出ない", async () => {
    const cases: [number, Record<string, unknown>, Record<string, string>][] = [
      [401, { code: "invalid_credentials" }, {}],
      [403, { code: "account_locked" }, {}],
      [429, { code: "rate_limited" }, { "Retry-After": "900" }],
      [422, { code: "weak_password", field: "password" }, {}],
    ];
    for (const [status, body, headers] of cases) {
      fetchMock.mockResolvedValueOnce(upstream(status, body, headers));
      const res = await LOGIN(jsonPost("/api/auth/login", loginBody, csrfHeaders()));
      expect(res.status).toBe(status);
      expect(await res.json()).toEqual(body);
      expect(findSetCookie(res, "sid")).toBeUndefined();
      expect(findSetCookie(res, "csrf_token")).toBeUndefined();
      expect(res.headers.get("Cache-Control")).toBe("no-store");
      expect(res.headers.get("Retry-After")).toBe(status === 429 ? "900" : null);
    }
  });

  it("許可しない詳細キー（locked_until・remaining など）は落とす", async () => {
    fetchMock.mockResolvedValue(upstream(403, { code: "account_locked", locked_until: "2026-10-24T00:00:00Z", remaining: 3 }));
    const res = await LOGIN(jsonPost("/api/auth/login", loginBody, csrfHeaders()));
    expect(await res.json()).toEqual({ code: "account_locked" });
  });

  it("Retry-After が数字でなければ透過しない", async () => {
    fetchMock.mockResolvedValue(upstream(429, { code: "rate_limited" }, { "Retry-After": "evil\tvalue" }));
    const res = await LOGIN(jsonPost("/api/auth/login", loginBody, csrfHeaders()));
    expect(res.status).toBe(429);
    expect(res.headers.get("Retry-After")).toBeNull();
  });

  it("接続不可は 503 upstream_unavailable（Set-Cookie なし）", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const res = await LOGIN(jsonPost("/api/auth/login", loginBody, csrfHeaders()));
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ code: "upstream_unavailable" });
    expect(findSetCookie(res, "sid")).toBeUndefined();
  });
});

describe("IT-BFF-030e 本文の上限（8KB）", () => {
  it("9000 バイトの本文は 413 payload_too_large（Content-Length あり・なし）。FastAPI は呼ばれない", async () => {
    const big = JSON.stringify({ email: "a@example.com", password: "x".repeat(9000) }); // pragma: allowlist secret
    const withLength = await LOGIN(jsonPost("/api/auth/login", big, csrfHeaders("", { "content-length": String(big.length) })));
    expect(withLength.status).toBe(413);
    expect(await withLength.json()).toEqual({ code: "payload_too_large" });

    // Content-Length を付けない（ストリーム本文）
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(big));
        controller.close();
      },
    });
    const noLength = await LOGIN(
      new Request("http://localhost:3000/api/auth/login", {
        method: "POST",
        body: stream,
        headers: csrfHeaders(),
        duplex: "half",
      } as RequestInit & { duplex: "half" }),
    );
    expect(noLength.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("IT-BFF-030f mass assignment", () => {
  it("login の本文に role・is_admin・session_token を足しても FastAPI に渡るのは email・password だけ", async () => {
    fetchMock.mockResolvedValue(upstream(200, loginOk));
    await LOGIN(jsonPost("/api/auth/login", { ...loginBody, role: "admin", is_admin: true, session_token: SID_OLD }, csrfHeaders()));
    expect(callOf(fetchMock).body).toEqual(loginBody);
  });
});

describe("IT-BFF-031 register・verify-email・password-reset の白リスト", () => {
  it("register: email・password・name・birth_date・gender・personalize_opt_in だけが渡る。202 の本文は透過", async () => {
    fetchMock.mockResolvedValue(upstream(202, { status: "accepted" }));
    const body = {
      email: "new@example.com",
      password: "dummy-password-1", // pragma: allowlist secret
      name: "デモ 太郎",
      birth_date: "1990-01-02",
      gender: "female",
      personalize_opt_in: true,
    };
    const res = await REGISTER(
      jsonPost("/api/auth/register", { ...body, role: "admin", email_verified_at: "2026-01-01", id: 1, anonymized_at: null }, csrfHeaders()),
    );
    expect(res.status).toBe(202);
    expect(await res.json()).toEqual({ status: "accepted" });
    expect(findSetCookie(res, "sid")).toBeUndefined(); // 自動ログインしない
    const c = callOf(fetchMock);
    expect(c.url).toBe("http://fastapi.test:8000/api/v1/auth/register"); // gitleaks:allow（テスト用 URL）
    expect(c.body).toEqual(body);
  });

  it("register: 任意項目が null・省略なら落とす。必須が文字列でない・任意の型が違う → 400 validation_error（FastAPI を呼ばない）", async () => {
    fetchMock.mockResolvedValue(upstream(202, { status: "accepted" }));
    await REGISTER(
      jsonPost("/api/auth/register", { email: "a@example.com", password: "dummy-password-1", name: "n", birth_date: null }, csrfHeaders()), // pragma: allowlist secret
    );
    expect(callOf(fetchMock).body).toEqual({ email: "a@example.com", password: "dummy-password-1", name: "n" }); // pragma: allowlist secret

    fetchMock.mockClear();
    for (const bad of [
      { email: 1, password: "dummy-password-1", name: "n" }, // pragma: allowlist secret
      { email: "a@example.com", password: ["x"], name: "n" },
      { email: "a@example.com", password: "dummy-password-1", name: "n", personalize_opt_in: "yes" }, // pragma: allowlist secret
      { email: "a@example.com", password: "dummy-password-1", name: "n", gender: 3 }, // pragma: allowlist secret
    ]) {
      const res = await REGISTER(jsonPost("/api/auth/register", bad, csrfHeaders()));
      expect(res.status).toBe(400);
      expect((await res.json()).code).toBe("validation_error");
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("verify-email: token だけが渡る。成功の本文は透過。token が文字列でなければ 400", async () => {
    fetchMock.mockResolvedValue(upstream(200, { verified: true }));
    const res = await VERIFY(jsonPost("/api/auth/verify-email", { token: SID_NEW, member_id: 3 }, csrfHeaders()));
    expect(await res.json()).toEqual({ verified: true });
    expect(callOf(fetchMock).body).toEqual({ token: SID_NEW });
    fetchMock.mockClear();
    const bad = await VERIFY(jsonPost("/api/auth/verify-email", { token: 123 }, csrfHeaders()));
    expect(bad.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("password-reset/request: email だけが渡る（常に 200 の応答を透過）", async () => {
    fetchMock.mockResolvedValue(upstream(200, { status: "accepted" }));
    const res = await RESET_REQ(jsonPost("/api/auth/password-reset/request", { email: "a@example.com", x: 1 }, csrfHeaders()));
    expect(res.status).toBe(200);
    expect(callOf(fetchMock).body).toEqual({ email: "a@example.com" });
    fetchMock.mockClear();
    expect((await RESET_REQ(jsonPost("/api/auth/password-reset/request", { email: null }, csrfHeaders()))).status).toBe(400);
  });

  it("password-reset/confirm: token・password だけが渡る。sid を発行しない（自動ログインしない）。404／422 は透過", async () => {
    fetchMock.mockResolvedValueOnce(upstream(200, { status: "ok" }));
    const ok = await RESET_CONFIRM(
      jsonPost("/api/auth/password-reset/confirm", { token: SID_NEW, password: "dummy-password-2", session_token: "x" }, csrfHeaders()), // pragma: allowlist secret
    );
    expect(ok.status).toBe(200);
    expect(findSetCookie(ok, "sid")).toBeUndefined();
    expect(callOf(fetchMock).body).toEqual({ token: SID_NEW, password: "dummy-password-2" }); // pragma: allowlist secret

    fetchMock.mockResolvedValueOnce(upstream(404, { code: "not_found" }));
    const notFound = await RESET_CONFIRM(jsonPost("/api/auth/password-reset/confirm", { token: SID_NEW, password: "dummy-password-2" }, csrfHeaders())); // pragma: allowlist secret
    expect(notFound.status).toBe(404);
    expect(await notFound.json()).toEqual({ code: "not_found" });

    fetchMock.mockResolvedValueOnce(upstream(422, { code: "weak_password", field: "password" }));
    const weak = await RESET_CONFIRM(jsonPost("/api/auth/password-reset/confirm", { token: SID_NEW, password: "password" }, csrfHeaders())); // pragma: allowlist secret
    expect(weak.status).toBe(422);
    expect(await weak.json()).toEqual({ code: "weak_password", field: "password" });
  });

  it("成功応答に cart_token・session_token 相当の項目があれば本文から除く", async () => {
    fetchMock.mockResolvedValue(upstream(200, { status: "ok", session_token: SID_NEW, cart_token: "c" }));
    const res = await RESET_CONFIRM(jsonPost("/api/auth/password-reset/confirm", { token: SID_NEW, password: "dummy-password-2" }, csrfHeaders())); // pragma: allowlist secret
    expect(await res.json()).toEqual({ status: "ok" });
  });

  it("壊れた JSON は 400 validation_error", async () => {
    const res = await LOGIN(jsonPost("/api/auth/login", "{not json", csrfHeaders()));
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
