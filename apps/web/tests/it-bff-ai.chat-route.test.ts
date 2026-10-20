import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { EnvValidationError, validateEnv } from "@/lib/env-validation";

// テスト設計書 IT-BFF-AI-01〜13（設計仕様書 P2 追補d 4.1〜4.5・7.2・7.4）。FastAPI は fetch をモックして差し替える。
// getEnv() は初回に process.env を読むので import 前に用意する。
process.env.API_BASE_URL = "http://fastapi.test:8000";
process.env.INTERNAL_TOKEN = "dummy-internal-token"; // gitleaks:allow // pragma: allowlist secret（テスト用ダミー）
process.env.IMAGE_BASE_URL = "http://localhost:3000";
process.env.APP_ENV = "development";
process.env.SESSION_COOKIE_DOMAIN = "";
process.env.TRUSTED_PROXY_HOPS = "0";

const CSRF = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"; // gitleaks:allow // pragma: allowlist secret
const OTHER_CSRF = "ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543210-_ZYXWV"; // gitleaks:allow // pragma: allowlist secret
const CHAT_TOKEN = "chatTokenAAAA_-0123456789abcdefghijklmnopqr"; // gitleaks:allow // pragma: allowlist secret（43 文字）
const NEW_TOKEN = "newChatTokenBBB_-0123456789abcdefghijklmnop"; // gitleaks:allow // pragma: allowlist secret（43 文字）

const replyOut = {
  chat_token: NEW_TOKEN,
  reply: {
    intent: "recommend",
    message: "春先に羽織れる軽めの商品を選びました。",
    products: [{ id: 12, name: "薄手パーカー", price_incl_tax: 2990, image_path: "/products/012/1.png", sold_out: false, reason: "薄手です。" }],
    sources: [],
    guide: null,
  },
  turns_used: 1,
  turns_limit: 10,
  notice: null,
};
const statusOut = { available: true, reason: null, provider: "stub", turns_limit: 10, message_max_chars: 300 };

function upstream(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

let POST_MESSAGES: typeof import("@/app/api/chat/messages/route").POST;
let GET_STATUS: typeof import("@/app/api/chat/status/route").GET;
let POST_RESET: typeof import("@/app/api/chat/reset/route").POST;

beforeAll(async () => {
  ({ POST: POST_MESSAGES } = await import("@/app/api/chat/messages/route"));
  ({ GET: GET_STATUS } = await import("@/app/api/chat/status/route"));
  ({ POST: POST_RESET } = await import("@/app/api/chat/reset/route"));
});

const fetchMock = vi.fn();
let warn: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
  fetchMock.mockReset();
});

const okHeaders = { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": CSRF, "Content-Type": "application/json" };
const URL_MESSAGES = "http://localhost:3000/api/chat/messages";

function post(body: unknown, headers: Record<string, string> = okHeaders, url = URL_MESSAGES) {
  return POST_MESSAGES(new Request(url, { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body), headers }));
}

/** JSON として正しい本文を、ちょうど `bytes` バイトにする（message は短く、余計なキーで埋める） */
function jsonOfBytes(bytes: number): string {
  const base = JSON.stringify({ message: "hello", pad: "" });
  return JSON.stringify({ message: "hello", pad: "a".repeat(bytes - base.length) });
}

function upstreamCall(index = 0) {
  const [url, init] = fetchMock.mock.calls[index] as [string, RequestInit];
  return { url, init, headers: new Headers(init.headers) };
}

describe("IT-BFF-AI-01 POST /api/chat/messages の CSRF", () => {
  const body = { message: "こんにちは" };

  it("CSRF ヘッダ無し・トークン不一致・Origin が他サイト・Sec-Fetch-Site: cross-site はすべて 403 forbidden。FastAPI は呼ばれない", async () => {
    const cases: Record<string, string>[] = [
      { cookie: `csrf_token=${CSRF}`, "Content-Type": "application/json" }, // ヘッダ無し
      { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": OTHER_CSRF, "Content-Type": "application/json" }, // 不一致
      { ...okHeaders, Origin: "https://evil.example" },
      { ...okHeaders, "Sec-Fetch-Site": "cross-site" },
      { "X-CSRF-Token": CSRF, "Content-Type": "application/json" }, // Cookie 無し
    ];
    for (const headers of cases) {
      const res = await post(body, headers);
      expect(res.status).toBe(403);
      expect(await res.json()).toEqual({ code: "forbidden" });
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("同一オリジンの Origin ＋ 正しいトークンは通る", async () => {
    fetchMock.mockImplementation(async () => upstream(200, replyOut));
    const res = await post(body, { ...okHeaders, Origin: "http://localhost:3000", "Sec-Fetch-Site": "same-origin" });
    expect(res.status).toBe(200);
  });
});

describe("IT-BFF-AI-02 本文サイズ", () => {
  it("8192 バイトちょうどは通す（形の検査へ進む）。8193 バイトと Content-Length の偽装は 413 payload_too_large", async () => {
    fetchMock.mockImplementation(async () => upstream(200, replyOut));
    const ok = jsonOfBytes(8192);
    expect(new TextEncoder().encode(ok).length).toBe(8192);
    expect((await post(ok)).status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fetchMock.mockClear();
    const tooBig = jsonOfBytes(8193);
    const r1 = await post(tooBig);
    expect(r1.status).toBe(413);
    expect(await r1.json()).toEqual({ code: "payload_too_large" });

    const r2 = await post(JSON.stringify({ message: "こんにちは" }), { ...okHeaders, "Content-Length": "9000" });
    expect(r2.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("IT-BFF-AI-03 message の形の検査", () => {
  it("空・空白のみは required、301 文字は too_long、数値は format。FastAPI は呼ばない", async () => {
    for (const [message, reason] of [
      ["", "required"],
      ["   ", "required"],
      ["　　", "required"],
      ["あ".repeat(301), "too_long"],
      [123, "format"],
    ] as const) {
      const res = await post({ message });
      expect(res.status).toBe(400);
      expect(await res.json()).toEqual({ code: "validation_error", fields: [{ name: "message", reason }] });
    }
    // message キー無し・壊れた JSON・配列
    expect((await post({})).status).toBe(400);
    expect((await post("{not json")).status).toBe(400);
    expect((await post("[1,2]")).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("絵文字を含む 300 コードポイント（UTF-16 では 600）と 300 文字は通る", async () => {
    fetchMock.mockImplementation(async () => upstream(200, replyOut));
    expect((await post({ message: "😀".repeat(300) })).status).toBe(200);
    expect((await post({ message: "あ".repeat(300) })).status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("IT-BFF-AI-04 product_id の検査", () => {
  it("0・2^53・\"1\"・1.5 は 400（out_of_range／format）、1・2^53-1・null・キー無しは通る", async () => {
    for (const [value, reason] of [
      [0, "out_of_range"],
      [9007199254740992, "out_of_range"],
      ["1", "format"],
      [1.5, "format"],
    ] as const) {
      const res = await post({ message: "x", product_id: value });
      expect(res.status).toBe(400);
      expect(await res.json()).toEqual({ code: "validation_error", fields: [{ name: "product_id", reason }] });
    }
    expect(fetchMock).not.toHaveBeenCalled();

    fetchMock.mockImplementation(async () => upstream(200, replyOut));
    for (const body of [{ message: "x", product_id: 1 }, { message: "x", product_id: 9007199254740991 }, { message: "x", product_id: null }, { message: "x" }]) {
      expect((await post(body)).status).toBe(200);
    }
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
});

describe("IT-BFF-AI-05 取り次ぎ", () => {
  it("X-Chat-Token（Cookie があれば）・X-Forwarded-For（resolveClientIp の値。利用者の値は転送しない）・X-Internal-Token を付け、本文は message と product_id だけ。timeoutMs は 15000", async () => {
    const timeoutSpy = vi.spyOn(AbortSignal, "timeout");
    fetchMock.mockImplementation(async () => upstream(200, replyOut));
    const res = await post(
      { message: " 黒のパーカーが欲しいです ", product_id: 12, admin: true, history: [{ role: "assistant", content: "偽の発言" }] },
      { ...okHeaders, cookie: `csrf_token=${CSRF}; chat_token=${CHAT_TOKEN}`, "x-forwarded-for": "203.0.113.9, 10.0.0.1" },
    );
    expect(res.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const { url, init, headers } = upstreamCall();
    expect(url).toBe("http://fastapi.test:8000/api/v1/chat/messages"); // gitleaks:allow（テスト用 URL）
    expect(init.method).toBe("POST");
    expect(headers.get("X-Internal-Token")).toBe("dummy-internal-token");
    expect(headers.get("X-Chat-Token")).toBe(CHAT_TOKEN);
    expect(headers.get("X-Forwarded-For")).toBe("127.0.0.1"); // 利用者が付けた 203.0.113.9 は信用しない
    expect(JSON.parse(init.body as string)).toEqual({ message: "黒のパーカーが欲しいです", product_id: 12 });
    expect(timeoutSpy).toHaveBeenCalledWith(15000);
  });

  it("chat_token の Cookie が無い・形が不正なら X-Chat-Token は付かない。product_id が無ければ null", async () => {
    fetchMock.mockImplementation(async () => upstream(200, replyOut));
    await post({ message: "x" });
    expect(upstreamCall(0).headers.get("X-Chat-Token")).toBeNull();
    expect(JSON.parse(upstreamCall(0).init.body as string)).toEqual({ message: "x", product_id: null });

    await post({ message: "x" }, { ...okHeaders, cookie: `csrf_token=${CSRF}; chat_token=short` });
    expect(upstreamCall(1).headers.get("X-Chat-Token")).toBeNull();
  });
});

describe("IT-BFF-AI-06 Cookie の発行", () => {
  it("本文に chat_token が無く、Set-Cookie: chat_token=…; HttpOnly; SameSite=Lax; Path=/; Max-Age=3600。Cache-Control: no-store。development では Secure なし", async () => {
    fetchMock.mockImplementation(async () => upstream(200, replyOut));
    const res = await post({ message: "x" });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).not.toHaveProperty("chat_token");
    expect(JSON.stringify(body)).not.toContain(NEW_TOKEN);
    expect(body.reply.products[0].price_incl_tax).toBe(2990);
    expect(body.turns_used).toBe(1);

    expect(res.headers.get("Cache-Control")).toBe("no-store");
    const cookies = res.headers.getSetCookie().filter((c) => c.startsWith("chat_token="));
    expect(cookies).toHaveLength(1);
    const c = cookies[0];
    expect(c.startsWith(`chat_token=${NEW_TOKEN};`)).toBe(true);
    for (const attr of ["HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=3600"]) expect(c).toContain(attr);
    expect(c).not.toContain("Secure");
    expect(c).not.toContain("Domain");
  });

  it("APP_ENV=production のときだけ Secure が付く", async () => {
    const prev = process.env.APP_ENV;
    process.env.APP_ENV = "production";
    vi.resetModules();
    try {
      const { POST } = await import("@/app/api/chat/messages/route");
      fetchMock.mockImplementation(async () => upstream(200, replyOut));
      const res = await POST(new Request(URL_MESSAGES, { method: "POST", body: JSON.stringify({ message: "x" }), headers: okHeaders }));
      const c = res.headers.getSetCookie().find((s) => s.startsWith("chat_token="))!;
      expect(c).toContain("Secure");
      expect(c).toContain("HttpOnly");
    } finally {
      process.env.APP_ENV = prev;
      vi.resetModules();
    }
  });

  it("形が不正な chat_token は Cookie に載せず、本文からも除く", async () => {
    fetchMock.mockResolvedValue(upstream(200, { ...replyOut, chat_token: "bad token;evil" }));
    const res = await post({ message: "x" });
    expect(res.headers.getSetCookie().some((c) => c.startsWith("chat_token="))).toBe(false);
    expect(await res.json()).not.toHaveProperty("chat_token");
  });
});

describe("IT-BFF-AI-07 Cookie の送出", () => {
  it("Cookie に chat_token があり、応答が chat_token: null なら X-Chat-Token に載り、Set-Cookie で再発行しない", async () => {
    fetchMock.mockImplementation(async () => upstream(200, { ...replyOut, chat_token: null }));
    const res = await post({ message: "x" }, { ...okHeaders, cookie: `csrf_token=${CSRF}; chat_token=${CHAT_TOKEN}` });
    expect(res.status).toBe(200);
    expect(upstreamCall().headers.get("X-Chat-Token")).toBe(CHAT_TOKEN);
    expect(res.headers.getSetCookie().some((c) => c.startsWith("chat_token="))).toBe(false);
    expect(await res.json()).not.toHaveProperty("chat_token");
  });
});

describe("IT-BFF-AI-08 エラーの透過", () => {
  it("status と {code, 許可したキー} がそのまま返る。FastAPI の余計なキーは落ちる。429 の Retry-After は数字のときだけ透過する", async () => {
    const cases: [number, Record<string, unknown>, Record<string, string>, Record<string, unknown>][] = [
      [409, { code: "turn_limit", limit: 10, detail: "x", token_hash: "h" }, {}, { code: "turn_limit", limit: 10 }],
      [429, { code: "rate_limited", detail: "x" }, { "Retry-After": "120" }, { code: "rate_limited" }],
      [502, { code: "llm_error", detail: "openai.APIError" }, {}, { code: "llm_error" }],
      [504, { code: "llm_timeout" }, {}, { code: "llm_timeout" }],
      [503, { code: "chat_unavailable" }, {}, { code: "chat_unavailable" }],
      [503, { code: "chat_daily_limit" }, {}, { code: "chat_daily_limit" }],
    ];
    for (const [status, body, headers, expected] of cases) {
      fetchMock.mockResolvedValueOnce(upstream(status, body, headers));
      const res = await post({ message: "x" });
      expect(res.status).toBe(status);
      expect(await res.json()).toEqual(expected);
      expect(res.headers.get("Retry-After")).toBe(status === 429 ? "120" : null);
      expect(res.headers.getSetCookie().some((c) => c.startsWith("chat_token="))).toBe(false);
    }

    for (const bad of ["abc", "Wed, 21 Oct 2026 07:28:00 GMT", "-5", "1.5"]) {
      fetchMock.mockResolvedValueOnce(upstream(429, { code: "rate_limited" }, { "Retry-After": bad }));
      const res = await post({ message: "x" });
      expect(res.status).toBe(429);
      expect(res.headers.get("Retry-After")).toBeNull();
    }
  });
});

describe("IT-BFF-AI-09 接続不可", () => {
  it("fetch が接続エラーなら 503 upstream_unavailable。例外メッセージ・接続先 URL を本文に含まない", async () => {
    fetchMock.mockRejectedValue(new TypeError("connect ECONNREFUSED fastapi.test:8000"));
    const res = await post({ message: "x" });
    expect(res.status).toBe(503);
    const text = await res.text();
    expect(JSON.parse(text)).toEqual({ code: "upstream_unavailable" });
    expect(text).not.toMatch(/ECONNREFUSED|fastapi|8000/);
  });

  it("15 秒を超える遅延は 503 upstream_unavailable（タイマーを進める）", async () => {
    vi.useFakeTimers();
    let timeoutMs = 0;
    vi.spyOn(AbortSignal, "timeout").mockImplementation((ms: number) => {
      timeoutMs = ms;
      const controller = new AbortController();
      setTimeout(() => controller.abort(new DOMException("timed out", "TimeoutError")), ms);
      return controller.signal;
    });
    fetchMock.mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => reject(init.signal?.reason));
        }),
    );
    const pending = post({ message: "x" });
    await vi.advanceTimersByTimeAsync(14_999);
    let settled = false;
    void pending.then(() => (settled = true));
    await vi.advanceTimersByTimeAsync(0);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    const res = await pending;
    expect(timeoutMs).toBe(15000);
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ code: "upstream_unavailable" });
  });
});

describe("IT-BFF-AI-10 GET /api/chat/status", () => {
  const req = (headers: Record<string, string> = {}) => new Request("http://localhost:3000/api/chat/status", { method: "GET", headers });

  it("CSRF なしで通る。本文は FastAPI の status のキーだけ。X-Internal-Token を付ける。csrf_token Cookie が無ければ発行する", async () => {
    fetchMock.mockImplementation(async () => upstream(200, { ...statusOut, model: "gpt-6-luna", secret: "x" }));
    const res = await GET_STATUS(req());
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(statusOut);
    expect(res.headers.get("Cache-Control")).toBe("no-store");

    const { url, init, headers } = upstreamCall();
    expect(url).toBe("http://fastapi.test:8000/api/v1/chat/status"); // gitleaks:allow（テスト用 URL）
    expect(init.method).toBe("GET");
    expect(headers.get("X-Internal-Token")).toBe("dummy-internal-token");
    expect(headers.get("X-Chat-Token")).toBeNull();
    expect(res.headers.getSetCookie().some((c) => c.startsWith("csrf_token="))).toBe(true);

    // 発行済みなら再発行しない
    fetchMock.mockImplementation(async () => upstream(200, statusOut));
    const again = await GET_STATUS(req({ cookie: `csrf_token=${CSRF}` }));
    expect(again.headers.getSetCookie().some((c) => c.startsWith("csrf_token="))).toBe(false);
  });

  it("接続不可は 503 upstream_unavailable。FastAPI のエラーは {code} で透過する", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("down"));
    const res = await GET_STATUS(req());
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ code: "upstream_unavailable" });

    fetchMock.mockResolvedValueOnce(upstream(401, { code: "unauthorized", detail: "x" }));
    const denied = await GET_STATUS(req());
    expect(denied.status).toBe(401);
    expect(await denied.json()).toEqual({ code: "unauthorized" });
  });
});

describe("IT-BFF-AI-11 POST /api/chat/reset", () => {
  const reset = (headers: Record<string, string>) =>
    POST_RESET(new Request("http://localhost:3000/api/chat/reset", { method: "POST", headers }));

  it("CSRF 有りは 200 {ok:true} と Set-Cookie: chat_token=; Max-Age=0。FastAPI は呼ばれない", async () => {
    const res = await reset({ cookie: `csrf_token=${CSRF}; chat_token=${CHAT_TOKEN}`, "X-CSRF-Token": CSRF });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    const c = res.headers.getSetCookie().find((s) => s.startsWith("chat_token="))!;
    expect(c.startsWith("chat_token=;")).toBe(true);
    expect(c).toContain("Max-Age=0");
    expect(c).toContain("Path=/");
    expect(c).toContain("HttpOnly");
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("CSRF 無し・不一致・他サイトの Origin は 403", async () => {
    for (const headers of [
      { cookie: `csrf_token=${CSRF}` },
      { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": OTHER_CSRF },
      { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": CSRF, Origin: "https://evil.example" },
    ] as Record<string, string>[]) {
      const res = await reset(headers);
      expect(res.status).toBe(403);
      expect(await res.json()).toEqual({ code: "forbidden" });
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("IT-BFF-AI-12 拒否ログ", () => {
  const KEYS = ["code", "event", "ip", "method", "path", "status"];
  const SECRETS = [CSRF, CHAT_TOKEN, "dummy-internal-token", "秘密の質問です", "cookie"];

  function lastLog(): Record<string, unknown> {
    const args = warn.mock.calls[warn.mock.calls.length - 1];
    expect(args).toHaveLength(1);
    const line = args[0] as string;
    expect(line).not.toContain("\n");
    const parsed = JSON.parse(line) as Record<string, unknown>;
    expect(Object.keys(parsed).sort()).toEqual(KEYS);
    for (const s of SECRETS) expect(line).not.toContain(s);
    return parsed;
  }

  it("403・413・400 で 1 行の構造化ログが出る（event・path・method・status・code・IP を丸めた値）。本文・Cookie・トークン・質問は出ない", async () => {
    const withCookie = { ...okHeaders, cookie: `csrf_token=${CSRF}; chat_token=${CHAT_TOKEN}`, "x-client-ip": "203.0.113.45" };

    await post({ message: "秘密の質問です" }, { cookie: `csrf_token=${CSRF}; chat_token=${CHAT_TOKEN}`, "Content-Type": "application/json" });
    expect(warn).toHaveBeenCalledTimes(1);
    expect(lastLog()).toMatchObject({ path: "/api/chat/messages", method: "POST", status: 403, code: "forbidden", ip: "127.0.0.0" });

    warn.mockClear();
    await post(jsonOfBytes(9000), withCookie);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(lastLog()).toMatchObject({ event: "payload_too_large", status: 413, code: "payload_too_large" });

    warn.mockClear();
    await post({ message: "" , note: "秘密の質問です" }, withCookie);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(lastLog()).toMatchObject({ event: "validation_rejected", status: 400, code: "validation_error" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("IT-BFF-AI-13 秘密", () => {
  it("NEXT_PUBLIC_OPENAI_API_KEY を環境に入れて validateEnv を呼ぶと EnvValidationError", () => {
    const env = {
      API_BASE_URL: "http://fastapi.test:8000",
      INTERNAL_TOKEN: "dummy-internal-token", // gitleaks:allow // pragma: allowlist secret
      IMAGE_BASE_URL: "http://localhost:3000",
      NEXT_PUBLIC_OPENAI_API_KEY: "dummy", // gitleaks:allow // pragma: allowlist secret
    };
    expect(() => validateEnv(env)).toThrow(EnvValidationError);
  });

  it("BFF の全応答（成功・各エラー・status・reset）に OPENAI・sk-・api の URL・内部トークンが無い", async () => {
    const texts: string[] = [];
    const collect = async (res: Response) => {
      texts.push(await res.text(), [...res.headers.entries()].map(([k, v]) => `${k}: ${v}`).join("\n"));
    };

    fetchMock.mockResolvedValueOnce(upstream(200, replyOut));
    await collect(await post({ message: "x" }));
    fetchMock.mockResolvedValueOnce(upstream(502, { code: "llm_error", detail: "openai.APIError sk-proj-abcdefghijklmnopqrstuvwxyz" }));
    await collect(await post({ message: "x" }));
    fetchMock.mockRejectedValueOnce(new TypeError("connect http://fastapi.test:8000 refused"));
    await collect(await post({ message: "x" }));
    await collect(await post({ message: "" }));
    await collect(await post({ message: "x" }, { "Content-Type": "application/json" }));
    fetchMock.mockResolvedValueOnce(upstream(200, statusOut));
    await collect(await GET_STATUS(new Request("http://localhost:3000/api/chat/status")));
    await collect(
      await POST_RESET(new Request("http://localhost:3000/api/chat/reset", { method: "POST", headers: { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": CSRF } })),
    );

    const all = texts.join("\n");
    expect(all.length).toBeGreaterThan(100);
    expect(all).not.toMatch(/openai/i);
    expect(all).not.toContain("sk-");
    expect(all).not.toContain("fastapi.test");
    expect(all).not.toContain("dummy-internal-token");
  });
});
