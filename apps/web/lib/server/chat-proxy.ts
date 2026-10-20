import "server-only";

import {
  buildChatTokenClearCookie,
  buildChatTokenCookie,
  CHAT_TOKEN_COOKIE,
  isChatTokenShape,
  readCookie,
} from "@/lib/cookie";
import type { ChatRequestPayload } from "@/lib/chat-validation";
import { apiFetch, UpstreamUnavailableError } from "@/lib/server/api";
import { issueCsrfCookieIfMissing } from "@/lib/server/csrf";
import { getEnv } from "@/lib/server/env";
import { clientIp, FORWARDED_FOR_HEADER } from "@/lib/server/order-proxy";
import type { ChatStatus } from "@/lib/types";

/**
 * AI アシスタント BFF の取り次ぎ（DS-API-040・041。設計仕様書 P2 追補d 4.1・4.4・7.4、テスト IT-BFF-AI-05〜11）。
 * - Cookie `chat_token`（HttpOnly）を `X-Chat-Token` に載せる。**chat_token は本文に出さない**（応答の値は Cookie にだけ載せ、本文から除く）
 * - `X-Forwarded-For` は `resolveClientIp` の値だけを送る（利用者が付けた値は転送しない。注文系と同じ）
 * - メッセージ送信だけ `timeoutMs` を 15000 にする（DS-DEC-95。LLM の 12 秒＋DB 処理より長く）。status は既定の 5 秒
 * - エラーは sanitizeErrorBody 済みの `{code, ...許可したキー}` をそのままの status で返す。429 の `Retry-After` は数字のときだけ透過する
 * - 接続不可は 503 `upstream_unavailable`。質問・応答の本文はログに出さない
 * - CSRF・本文サイズ・形の検査は各 Route Handler が先頭で行う（ここには置かない）
 */

export const CHAT_TOKEN_HEADER = "X-Chat-Token";
/** メッセージ送信の BFF タイムアウト（DS-DEC-95） */
export const CHAT_MESSAGE_TIMEOUT_MS = 15000;

const STATUS_KEYS = ["available", "reason", "provider", "turns_limit", "message_max_chars"] as const;

function noStore(): Headers {
  return new Headers({ "Cache-Control": "no-store" });
}

function unavailable(headers: Headers): Response {
  return Response.json({ code: "upstream_unavailable" }, { status: 503, headers });
}

function internalError(path: string, err: unknown, headers: Headers): Response {
  // 質問・応答の本文は出さない。メッセージだけ
  console.error("[api/chat] unexpected error", { path, reason: err instanceof Error ? err.message : String(err) });
  return Response.json({ code: "internal_error", message: "処理中にエラーが発生しました" }, { status: 500, headers });
}

/** 本文から `chat_token` を除く（最上位だけ）。オブジェクト以外はそのまま返す */
export function stripChatToken<T>(data: T): T {
  if (typeof data !== "object" || data === null || Array.isArray(data) || !("chat_token" in data)) return data;
  const { chat_token: _omitted, ...rest } = data as Record<string, unknown>;
  void _omitted;
  return rest as T;
}

/** GET /api/chat/status。CSRF 検証なし（読み取り専用）。csrf_token Cookie が未発行ならここで発行する（以降の POST 用） */
export async function proxyChatStatus(request: Request): Promise<Response> {
  const headers = noStore();
  let result;
  try {
    result = await apiFetch<unknown>("/chat/status", { method: "GET" });
  } catch (err) {
    if (err instanceof UpstreamUnavailableError) return unavailable(headers);
    return internalError("/chat/status", err, headers);
  }
  if (!result.ok) return Response.json(result.error, { status: result.status, headers });

  const src = result.data;
  if (typeof src !== "object" || src === null || Array.isArray(src)) {
    return Response.json({ code: "upstream_error" }, { status: 502, headers });
  }
  const picked: Record<string, unknown> = {};
  for (const key of STATUS_KEYS) picked[key] = (src as Record<string, unknown>)[key] ?? null;

  const csrfCookie = issueCsrfCookieIfMissing(request);
  if (csrfCookie) headers.append("Set-Cookie", csrfCookie);
  return Response.json(picked as unknown as ChatStatus, { status: 200, headers });
}

/** POST /api/chat/messages の取り次ぎ。`payload` は検査済みの `{message, product_id}` */
export async function proxyChatMessage(request: Request, payload: ChatRequestPayload): Promise<Response> {
  const headers = noStore();
  const cookieToken = readCookie(request.headers.get("cookie"), CHAT_TOKEN_COOKIE);
  const upstreamHeaders: Record<string, string> = { [FORWARDED_FOR_HEADER]: clientIp(request) };
  if (isChatTokenShape(cookieToken)) upstreamHeaders[CHAT_TOKEN_HEADER] = cookieToken;

  let result;
  try {
    result = await apiFetch<unknown>("/chat/messages", {
      method: "POST",
      json: { message: payload.message, product_id: payload.product_id },
      headers: upstreamHeaders,
      timeoutMs: CHAT_MESSAGE_TIMEOUT_MS,
    });
  } catch (err) {
    if (err instanceof UpstreamUnavailableError) return unavailable(headers);
    return internalError("/chat/messages", err, headers);
  }

  if (!result.ok) {
    // 429 rate_limited の Retry-After は画面の待ち秒数に使うので透過する（数字のときだけ）
    if (result.status === 429 && result.retryAfter && /^\d{1,6}$/.test(result.retryAfter.trim())) {
      headers.set("Retry-After", result.retryAfter.trim());
    }
    return Response.json(result.error, { status: result.status, headers });
  }

  // 新しいセッションのときだけ chat_token が文字列で返る。Cookie に載せ、本文からは除く
  const upstreamToken = (result.data as { chat_token?: unknown } | null)?.chat_token;
  if (isChatTokenShape(typeof upstreamToken === "string" ? upstreamToken : null)) {
    headers.append("Set-Cookie", buildChatTokenCookie(upstreamToken as string, getEnv().APP_ENV));
  }
  return Response.json(stripChatToken(result.data), { status: result.status, headers });
}

/** POST /api/chat/reset。FastAPI は呼ばず、会話トークン Cookie を消す（次の質問で新しいセッションになる） */
export function chatResetResponse(): Response {
  const headers = noStore();
  headers.append("Set-Cookie", buildChatTokenClearCookie(getEnv().APP_ENV));
  return Response.json({ ok: true }, { status: 200, headers });
}
