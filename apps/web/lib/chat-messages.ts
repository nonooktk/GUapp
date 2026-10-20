/**
 * AI アシスタントの失敗時の文言（設計仕様書 P2 追補d 6.3・テスト UT-WEB-AI-07）。
 * エラーコード・HTTP status → 利用者向けの文言と、画面の状態（再送待ち・待機・往復上限・利用不可）。
 * api の内部情報（例外名・メッセージ）は文言に出さない。
 */

import { CHAT_MESSAGE_MAX_CHARS } from "@/lib/chat-validation";
import type { ApiErrorBody } from "@/lib/types";

export const CHAT_TURN_LIMIT_DEFAULT = 10;
/** `Retry-After` が読めないときの待ち秒数 */
export const CHAT_WAIT_FALLBACK_SEC = 60;
const CHAT_WAIT_MAX_SEC = 3600;

export const CHAT_GREETING = "商品選びと、よくある質問にお答えします。";
export const CHAT_NOTICE_TEXT = "AI の回答は誤りを含むことがあります。氏名・住所・電話番号などは入力しないでください。";
export const CHAT_MASKED_NOTICE = "個人情報らしき文字列は伏せて処理しました";

/** 質問の例ボタン（押すと、この固定の文を入力欄に入れて送信する） */
export const CHAT_EXAMPLES = ["春に羽織れるアウター", "送料は？", "返品は？"] as const;

/** 失敗・案内で出すリンク（FAQ・企業情報） */
export const CHAT_GUIDE_LINKS = [
  { label: "よくある質問", href: "/contents/faq" },
  { label: "企業情報", href: "/contents/company" },
] as const;

/** `notice` は文言だけを出す（再送や案内のボタンなし。「新しい相談」の失敗で使う） */
export type ChatFailureKind = "retry" | "wait" | "turn_limit" | "unavailable" | "validation" | "notice";

export interface ChatFailure {
  kind: ChatFailureKind;
  message: string;
  /** kind=wait のとき、送信を止める秒数 */
  waitSec?: number;
  /** kind=turn_limit のとき、往復の上限 */
  limit?: number;
}

const RETRY_MESSAGE = "うまく答えられませんでした。もう一度送るか、よくある質問をご覧ください";

/** 429 の待ち秒数。`Retry-After` が正の整数でなければ既定値。大きすぎる値は 1 時間で丸める */
export function normalizeWaitSec(retryAfterSec: number | null | undefined): number {
  if (typeof retryAfterSec !== "number" || !Number.isFinite(retryAfterSec) || retryAfterSec < 1) return CHAT_WAIT_FALLBACK_SEC;
  return Math.min(Math.ceil(retryAfterSec), CHAT_WAIT_MAX_SEC);
}

/** 400（形の不正）の文言 */
export function chatValidationMessage(reason: string | null | undefined): string {
  if (reason === "required") return "質問を入力してください";
  if (reason === "too_long") return `質問は ${CHAT_MESSAGE_MAX_CHARS} 文字以内で入力してください`;
  return "入力内容を確認してください";
}

/** status が利用不可のときの文言（reason は `disabled`・`daily_limit`） */
export function chatUnavailableMessage(reason: string | null | undefined): string {
  return reason === "daily_limit" ? "現在利用できません。しばらくしてからお試しください" : "現在利用できません";
}

/**
 * 送信の失敗を、表示する文言と状態に直す。`status=0` は通信失敗（fetch の例外）。
 * 未知のコード・403・413 などは汎用の失敗文言（再送待ち）にする。
 */
export function describeChatFailure(status: number, body: ApiErrorBody | null, retryAfterSec: number | null = null): ChatFailure {
  const code = body?.code;
  if (status === 429) {
    const waitSec = normalizeWaitSec(retryAfterSec);
    return {
      kind: "wait",
      message: `短い時間に多くの質問が送られました。${waitSec} 秒後にもう一度お試しください`,
      waitSec,
    };
  }
  if (status === 409 && code === "turn_limit") {
    const limit = typeof body?.limit === "number" && body.limit > 0 ? body.limit : CHAT_TURN_LIMIT_DEFAULT;
    return { kind: "turn_limit", message: `この相談の上限（${limit} 往復）に達しました。新しい相談を始めてください`, limit };
  }
  if (status === 503 && code === "chat_daily_limit") {
    return { kind: "unavailable", message: chatUnavailableMessage("daily_limit") };
  }
  if (status === 503 && code === "chat_unavailable") {
    return { kind: "unavailable", message: chatUnavailableMessage("disabled") };
  }
  if (status === 400 && code === "validation_error") {
    const fields = Array.isArray(body?.fields) ? (body.fields as { name?: unknown; reason?: unknown }[]) : [];
    const first = fields.find((f) => f && f.name === "message") ?? fields[0];
    return { kind: "validation", message: chatValidationMessage(typeof first?.reason === "string" ? first.reason : null) };
  }
  return { kind: "retry", message: RETRY_MESSAGE };
}
