import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { CSRF, csrfHeaders, jsonPost, SID_NEW, SID_OLD, upstream } from "./helpers/bff";

// ST-SEC-44（セッションの盗用）・ST-SEC-53（ログイン・個人情報がログに出ない）・ST-SEC-49（mass assignment）の BFF 側。設計仕様書 7.1
let LOGIN: (request: Request) => Promise<Response>;
let REGISTER: (request: Request) => Promise<Response>;
let RESET_CONFIRM: (request: Request) => Promise<Response>;
beforeAll(async () => {
  ({ POST: LOGIN } = await import("@/app/api/auth/login/route"));
  ({ POST: REGISTER } = await import("@/app/api/auth/register/route"));
  ({ POST: RESET_CONFIRM } = await import("@/app/api/auth/password-reset/confirm/route"));
});

const fetchMock = vi.fn();
let logs: string[];
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  logs = [];
  for (const m of ["log", "info", "warn", "error"] as const) {
    vi.spyOn(console, m).mockImplementation((...args: unknown[]) => {
      logs.push(args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" "));
    });
  }
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  fetchMock.mockReset();
});

const EMAIL = "private-person@example.com";
const PASSWORD = "very-secret-password-9"; // pragma: allowlist secret

describe("ST-SEC-44 / 53 BFF がセッション・パスワード・メールを漏らさない", () => {
  it("ログイン成功の応答（本文・ヘッダー）に session_token の値が出るのは HttpOnly の sid Cookie だけ", async () => {
    fetchMock.mockResolvedValue(upstream(200, { session_token: SID_NEW, member: { name: "n", email_verified: true } }));
    const res = await LOGIN(jsonPost("/api/auth/login", { email: EMAIL, password: PASSWORD }, csrfHeaders()));
    const body = await res.text();
    expect(body).not.toContain(SID_NEW);
    const cookies = res.headers.getSetCookie();
    expect(cookies.filter((c) => c.includes(SID_NEW))).toHaveLength(1);
    expect(cookies.find((c) => c.includes(SID_NEW))).toContain("HttpOnly");
    // csrf_token はクライアントが読む Cookie（HttpOnly なし）で、ログイン前と値が異なる
    const csrf = cookies.find((c) => c.startsWith("csrf_token="))!;
    expect(csrf).not.toContain("HttpOnly");
    expect(csrf).not.toContain(CSRF);
  });

  it("失敗（接続不可・予期しない例外・契約違反）でもログにメール・パスワード・トークンを書かない", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    await LOGIN(jsonPost("/api/auth/login", { email: EMAIL, password: PASSWORD }, csrfHeaders(`sid=${SID_OLD}`)));
    fetchMock.mockResolvedValueOnce(upstream(200, { member: {} })); // session_token 欠落
    await LOGIN(jsonPost("/api/auth/login", { email: EMAIL, password: PASSWORD }, csrfHeaders()));
    fetchMock.mockResolvedValueOnce(upstream(404, { code: "not_found" }));
    await RESET_CONFIRM(jsonPost("/api/auth/password-reset/confirm", { token: SID_NEW, password: PASSWORD }, csrfHeaders()));
    // CSRF 拒否（拒否ログ）
    await LOGIN(jsonPost("/api/auth/login", { email: EMAIL, password: PASSWORD }, { "Content-Type": "application/json" }));

    expect(logs.length).toBeGreaterThan(0);
    const all = logs.join("\n");
    for (const secret of [EMAIL, PASSWORD, SID_NEW, SID_OLD, CSRF]) expect(all).not.toContain(secret);
  });
});

describe("ST-SEC-49 mass assignment（BFF）", () => {
  it("登録の本文に role・is_admin・email_verified_at・id・anonymized_at を付けても FastAPI へ渡らない", async () => {
    fetchMock.mockResolvedValue(upstream(202, { status: "accepted" }));
    await REGISTER(
      jsonPost("/api/auth/register", { email: EMAIL, password: PASSWORD, name: "n", role: "admin", is_admin: true, email_verified_at: "2026-01-01", id: 1, anonymized_at: null }, csrfHeaders()),
    );
    const sent = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(Object.keys(sent).sort()).toEqual(["email", "name", "password"]);
  });
});
