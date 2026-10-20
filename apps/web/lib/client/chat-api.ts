import { CSRF_HEADER } from "@/lib/csrf-validation";
import { readCsrfCookie } from "@/lib/client/cart-api";
import type {
  ApiErrorBody,
  ChatIntent,
  ChatLink,
  ChatMessageResponse,
  ChatProduct,
  ChatProvider,
  ChatReply,
  ChatStatus,
} from "@/lib/types";

/**
 * ブラウザから BFF（/api/chat/*）を呼ぶ薄いクライアント（設計仕様書 P2 追補d 4.1・6.6、テスト UT-WEB-AI-08）。
 * - 状態変更（messages・reset）は `X-CSRF-Token` に Cookie `csrf_token` の値を載せる。未発行なら `GET /api/chat/status` が発行する
 *   （カートを作らないため。status は読み取り専用で CSRF 不要）
 * - 失敗は ChatApiError（status と `{code,...}` 本文、`Retry-After` の秒数）。通信失敗・壊れた本文は status 0／本文 null
 * - 応答は画面が使う形（`ChatReply`）に整える。リンクは `/` で始まるサイト内のパスだけ通す
 */

export class ChatApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: ApiErrorBody | null,
    readonly retryAfterSec: number | null = null,
  ) {
    super(`chat api ${status} ${body?.code ?? ""}`);
    this.name = "ChatApiError";
  }
}

/** `Retry-After` を秒（正の整数）で読む。数字でなければ null */
export function parseRetryAfter(value: string | null): number | null {
  if (value === null || !/^\d{1,6}$/.test(value.trim())) return null;
  const n = Number(value.trim());
  return n >= 1 ? n : null;
}

async function parseJson(res: Response): Promise<unknown> {
  const text = await res.text().catch(() => "");
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function asErrorBody(value: unknown): ApiErrorBody | null {
  return typeof value === "object" && value !== null && typeof (value as { code?: unknown }).code === "string"
    ? (value as ApiErrorBody)
    : null;
}

async function requestJson(input: string, init: RequestInit): Promise<unknown> {
  let res: Response;
  try {
    res = await fetch(input, { ...init, credentials: "same-origin", cache: "no-store" });
  } catch {
    throw new ChatApiError(0, null);
  }
  const data = await parseJson(res);
  if (!res.ok) {
    throw new ChatApiError(res.status, asErrorBody(data), parseRetryAfter(res.headers.get("Retry-After")));
  }
  if (data === null) throw new ChatApiError(res.status, { code: "bad_response" });
  return data;
}

// ---- 応答の整形 ----

const INTENTS: readonly ChatIntent[] = ["recommend", "faq", "clarify", "out_of_scope"];
const PROVIDERS: readonly ChatProvider[] = ["openai", "stub", "none"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** サイト内のパスだけ許可する（`//evil` や `https://…` は不可） */
export function isSafeInternalHref(href: unknown): href is string {
  return typeof href === "string" && /^\/(?!\/)[A-Za-z0-9\-._~/?=&%]*$/.test(href);
}

function toLinks(value: unknown, labelKey: "title" | "label"): ChatLink[] {
  if (!Array.isArray(value)) return [];
  const out: ChatLink[] = [];
  for (const item of value) {
    if (!isRecord(item)) continue;
    const label = item[labelKey] ?? item.label ?? item.title;
    if (typeof label === "string" && isSafeInternalHref(item.href)) out.push({ label, href: item.href });
  }
  return out;
}

function toProducts(value: unknown): ChatProduct[] {
  if (!Array.isArray(value)) return [];
  const out: ChatProduct[] = [];
  for (const p of value) {
    if (!isRecord(p)) continue;
    if (typeof p.id !== "number" || !Number.isSafeInteger(p.id) || p.id < 1) continue;
    if (typeof p.name !== "string" || typeof p.price_incl_tax !== "number") continue;
    out.push({
      id: p.id,
      name: p.name,
      price_incl_tax: p.price_incl_tax,
      image_path: typeof p.image_path === "string" ? p.image_path : null,
      sold_out: p.sold_out === true,
      reason: typeof p.reason === "string" ? p.reason : "",
    });
  }
  return out;
}

function toReply(value: unknown): ChatReply | null {
  if (!isRecord(value) || typeof value.message !== "string") return null;
  const intent = INTENTS.includes(value.intent as ChatIntent) ? (value.intent as ChatIntent) : "clarify";
  return {
    intent,
    message: value.message,
    products: toProducts(value.products),
    sources: toLinks(value.sources, "title"),
    guide: isRecord(value.guide) ? toLinks(value.guide.links, "label") : [],
  };
}

function toInt(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.trunc(value) : fallback;
}

/** GET /api/chat/status */
export async function getChatStatus(): Promise<ChatStatus> {
  const data = await requestJson("/api/chat/status", { method: "GET", headers: { Accept: "application/json" } });
  if (!isRecord(data) || typeof data.available !== "boolean") throw new ChatApiError(200, { code: "bad_response" });
  return {
    available: data.available,
    reason: data.reason === "disabled" || data.reason === "daily_limit" ? data.reason : null,
    provider: PROVIDERS.includes(data.provider as ChatProvider) ? (data.provider as ChatProvider) : "none",
    turns_limit: toInt(data.turns_limit, 10),
    message_max_chars: toInt(data.message_max_chars, 300),
  };
}

/** CSRF トークンを返す。未発行なら `GET /api/chat/status` で発行させてから読む */
async function ensureChatCsrfToken(): Promise<string> {
  let token = readCsrfCookie(document.cookie);
  if (token) return token;
  await getChatStatus();
  token = readCsrfCookie(document.cookie);
  if (!token) throw new ChatApiError(403, { code: "forbidden" });
  return token;
}

/** POST /api/chat/messages。`productId` は商品詳細から開いたときの文脈（無ければ null） */
export async function sendChatMessage(input: { message: string; productId: number | null }): Promise<ChatMessageResponse> {
  const csrf = await ensureChatCsrfToken();
  const data = await requestJson("/api/chat/messages", {
    method: "POST",
    headers: { [CSRF_HEADER]: csrf, Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ message: input.message, product_id: input.productId }),
  });
  const reply = isRecord(data) ? toReply(data.reply) : null;
  if (!isRecord(data) || !reply) throw new ChatApiError(200, { code: "bad_response" });
  return {
    reply,
    turns_used: toInt(data.turns_used, 0),
    turns_limit: toInt(data.turns_limit, 10),
    notice: data.notice === "masked" ? "masked" : null,
  };
}

/** POST /api/chat/reset。Cookie `chat_token` を消す（次の質問で新しいセッション） */
export async function resetChat(): Promise<void> {
  const csrf = await ensureChatCsrfToken();
  await requestJson("/api/chat/reset", { method: "POST", headers: { [CSRF_HEADER]: csrf, Accept: "application/json" } });
}
