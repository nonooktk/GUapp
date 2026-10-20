/**
 * AI アシスタントの入力検査（設計仕様書 P2 追補d 4.3・4.4・DS-DEC-96、テスト UT-WEB-AI-01・IT-BFF-AI-03/04）。
 * 純粋関数。BFF（app/api/chat/messages）と画面（ChatProvider）で共有するため `server-only` は付けない。
 * 文字数は FastAPI（Python の `len(str)`）と同じ「コードポイント数」で数える（絵文字のサロゲートペアは 1 文字）。
 */

export const CHAT_MESSAGE_MAX_CHARS = 300;
/** FastAPI は 9223372036854775807 まで受けるが、JSON の数値は JS で安全に扱える 2^53-1 までに絞る */
export const CHAT_PRODUCT_ID_MAX = Number.MAX_SAFE_INTEGER;

export type ChatMessageIssue = "required" | "too_long" | "format";
export type ChatProductIdIssue = "out_of_range" | "format";

/** コードポイント数（`[...text].length`） */
export function countCodePoints(text: string): number {
  let n = 0;
  for (const _ of text) {
    void _;
    n += 1;
  }
  return n;
}

/** 前後の空白（全角空白を含む）を除いた質問、または理由を返す */
export function validateChatMessage(value: unknown): { ok: true; value: string } | { ok: false; reason: ChatMessageIssue } {
  if (value === undefined || value === null) return { ok: false, reason: "required" };
  if (typeof value !== "string") return { ok: false, reason: "format" };
  const trimmed = value.trim();
  if (trimmed === "") return { ok: false, reason: "required" };
  if (countCodePoints(trimmed) > CHAT_MESSAGE_MAX_CHARS) return { ok: false, reason: "too_long" };
  return { ok: true, value: trimmed };
}

/** `product_id`。キー無し・null は文脈なし（null）として通す */
export function validateChatProductId(value: unknown): { ok: true; value: number | null } | { ok: false; reason: ChatProductIdIssue } {
  if (value === undefined || value === null) return { ok: true, value: null };
  if (typeof value !== "number" || !Number.isInteger(value)) return { ok: false, reason: "format" };
  if (value < 1 || value > CHAT_PRODUCT_ID_MAX) return { ok: false, reason: "out_of_range" };
  return { ok: true, value };
}

export interface ChatRequestPayload {
  message: string;
  product_id: number | null;
}

export type ChatRequestCheck =
  | { ok: true; payload: ChatRequestPayload }
  | { ok: false; fields: { name: string; reason: string }[] };

/** BFF の本文検査。許可したキー（`message`・`product_id`）以外は落とす */
export function validateChatRequestBody(body: Record<string, unknown>): ChatRequestCheck {
  const fields: { name: string; reason: string }[] = [];
  const message = validateChatMessage(body.message);
  if (!message.ok) fields.push({ name: "message", reason: message.reason });
  const productId = validateChatProductId(body.product_id);
  if (!productId.ok) fields.push({ name: "product_id", reason: productId.reason });
  if (fields.length > 0 || !message.ok || !productId.ok) return { ok: false, fields };
  return { ok: true, payload: { message: message.value, product_id: productId.value } };
}
