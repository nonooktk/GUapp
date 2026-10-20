import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chatUnavailableMessage, chatValidationMessage, describeChatFailure } from "@/lib/chat-messages";
import { clearCookies, createChatFetch, json, renderChat, setCsrfCookie, STATUS_OK } from "./helpers/chat";

// テスト設計書 UT-WEB-AI-07: lib/chat-messages.ts と失敗の表示（設計仕様書 P2 追補d 6.3）。
// 429（Retry-After 90）・409 turn_limit・503 両方・502・504・400・通信失敗・未知のコード。内部情報を文言に出さない。失敗の表示は role="alert"。

describe("UT-WEB-AI-07 describeChatFailure", () => {
  it("429 は Retry-After の秒数を文言に入れ、待機にする（秒数が読めなければ 60 秒、大きすぎれば 1 時間）", () => {
    expect(describeChatFailure(429, { code: "rate_limited" }, 90)).toEqual({
      kind: "wait",
      message: "短い時間に多くの質問が送られました。90 秒後にもう一度お試しください",
      waitSec: 90,
    });
    expect(describeChatFailure(429, { code: "rate_limited" }, null).waitSec).toBe(60);
    expect(describeChatFailure(429, { code: "rate_limited" }, 0).waitSec).toBe(60);
    expect(describeChatFailure(429, { code: "rate_limited" }, 999999).waitSec).toBe(3600);
  });

  it("409 turn_limit は往復上限（limit を文言に入れる。無ければ 10）", () => {
    expect(describeChatFailure(409, { code: "turn_limit", limit: 10 })).toMatchObject({
      kind: "turn_limit",
      message: "この相談の上限（10 往復）に達しました。新しい相談を始めてください",
      limit: 10,
    });
    expect(describeChatFailure(409, { code: "turn_limit" }).limit).toBe(10);
  });

  it("503 chat_daily_limit・chat_unavailable は利用不可（文言が異なる）", () => {
    expect(describeChatFailure(503, { code: "chat_daily_limit" })).toEqual({
      kind: "unavailable",
      message: "現在利用できません。しばらくしてからお試しください",
    });
    expect(describeChatFailure(503, { code: "chat_unavailable" })).toEqual({ kind: "unavailable", message: "現在利用できません" });
    expect(chatUnavailableMessage("daily_limit")).toContain("しばらくしてから");
    expect(chatUnavailableMessage("disabled")).toBe("現在利用できません");
  });

  it("502・504・503 upstream_unavailable・通信失敗（status 0）・未知のコードは汎用の失敗文言（再送待ち）", () => {
    const generic = "うまく答えられませんでした。もう一度送るか、よくある質問をご覧ください";
    for (const [status, body] of [
      [502, { code: "llm_error" }],
      [504, { code: "llm_timeout" }],
      [503, { code: "upstream_unavailable" }],
      [0, null],
      [403, { code: "forbidden" }],
      [413, { code: "payload_too_large" }],
      [500, { code: "something_new", message: "OpenAIError: secret detail" }],
      [418, { code: "teapot" }],
    ] as const) {
      expect(describeChatFailure(status, body)).toEqual({ kind: "retry", message: generic });
    }
  });

  it("400 validation_error は理由ごとの文言（message のフィールドを優先）", () => {
    const f = describeChatFailure(400, { code: "validation_error", fields: [{ name: "product_id", reason: "out_of_range" }, { name: "message", reason: "required" }] });
    expect(f).toEqual({ kind: "validation", message: "質問を入力してください" });
    expect(chatValidationMessage("too_long")).toBe("質問は 300 文字以内で入力してください");
    expect(chatValidationMessage("format")).toBe("入力内容を確認してください");
  });

  it("文言に api の内部情報（例外名・メッセージ・モデル名）が出ない", () => {
    const hostile = { code: "llm_error", message: "openai.APIError sk-proj-xxxxxxxx gpt-6-luna Traceback", detail: "internal" };
    for (const status of [400, 409, 429, 500, 502, 503, 504]) {
      const m = describeChatFailure(status, hostile, 5).message;
      expect(m).not.toMatch(/openai|sk-|gpt|Traceback|internal/i);
    }
  });
});

describe("UT-WEB-AI-07 失敗の表示", () => {
  let chat: ReturnType<typeof createChatFetch>;
  beforeEach(() => {
    chat = createChatFetch();
    chat.status(() => json(200, STATUS_OK));
    vi.stubGlobal("fetch", chat.mock);
    setCsrfCookie();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    clearCookies();
  });

  it("失敗は role=alert で出し、⚠ は装飾（読み上げない）。api の message は画面に出ない", async () => {
    renderChat();
    fireEvent.click(screen.getByRole("button", { name: "AI アシスタントに相談する" }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    chat.messages(() => json(502, { code: "llm_error", message: "boom internal detail" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "こんにちは" } });
    fireEvent.click(screen.getByRole("button", { name: "送信" }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("⚠");
    expect(alert.querySelector('[aria-hidden="true"]')).toHaveTextContent("⚠");
    expect(alert).not.toHaveTextContent("boom");
  });
});
