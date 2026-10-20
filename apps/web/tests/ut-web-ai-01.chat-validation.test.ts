import { describe, expect, it } from "vitest";
import {
  CHAT_MESSAGE_MAX_CHARS,
  countCodePoints,
  validateChatMessage,
  validateChatProductId,
  validateChatRequestBody,
} from "@/lib/chat-validation";

// テスト設計書 UT-WEB-AI-01: lib/chat-validation.ts の境界（空・空白のみ・全角空白のみ・1 / 300 / 301 文字・絵文字 300 個・改行）。
// 設計仕様書 P2 追補d 4.3・4.4。文字数は FastAPI（Python の len）と同じコードポイント数。

describe("UT-WEB-AI-01 validateChatMessage", () => {
  it("空・空白のみ・全角空白のみ・タブ改行のみは required", () => {
    for (const v of ["", " ", "   ", "　", "　 　", "\n\t "]) {
      expect(validateChatMessage(v)).toEqual({ ok: false, reason: "required" });
    }
  });

  it("キー無し（undefined）・null は required、文字列以外は format", () => {
    expect(validateChatMessage(undefined)).toEqual({ ok: false, reason: "required" });
    expect(validateChatMessage(null)).toEqual({ ok: false, reason: "required" });
    for (const v of [123, true, {}, [], ["a"]]) {
      expect(validateChatMessage(v)).toEqual({ ok: false, reason: "format" });
    }
  });

  it("1 文字と 300 文字は通り、301 文字は too_long", () => {
    expect(validateChatMessage("あ")).toEqual({ ok: true, value: "あ" });
    expect(validateChatMessage("あ".repeat(300))).toEqual({ ok: true, value: "あ".repeat(300) });
    expect(validateChatMessage("あ".repeat(301))).toEqual({ ok: false, reason: "too_long" });
  });

  it("絵文字（サロゲートペア）300 個は通り、301 個は too_long（コードポイントで数える）", () => {
    expect("😀".repeat(300).length).toBe(600); // UTF-16 では 600 だが
    expect(countCodePoints("😀".repeat(300))).toBe(300);
    expect(validateChatMessage("😀".repeat(300)).ok).toBe(true);
    expect(validateChatMessage("😀".repeat(301))).toEqual({ ok: false, reason: "too_long" });
  });

  it("前後の空白（全角を含む）は除いて数える。改行は許し、中身は保つ", () => {
    const padded = `　 ${"あ".repeat(300)} 　\n`;
    expect(validateChatMessage(padded)).toEqual({ ok: true, value: "あ".repeat(300) });
    expect(validateChatMessage("1 行目\n2 行目")).toEqual({ ok: true, value: "1 行目\n2 行目" });
    expect(CHAT_MESSAGE_MAX_CHARS).toBe(300);
  });
});

describe("UT-WEB-AI-01 validateChatProductId / validateChatRequestBody", () => {
  it("product_id: キー無し・null は文脈なし、1 と 2^53-1 は通り、0・2^53 は out_of_range、文字列・小数は format", () => {
    expect(validateChatProductId(undefined)).toEqual({ ok: true, value: null });
    expect(validateChatProductId(null)).toEqual({ ok: true, value: null });
    expect(validateChatProductId(1)).toEqual({ ok: true, value: 1 });
    expect(validateChatProductId(9007199254740991)).toEqual({ ok: true, value: 9007199254740991 });
    expect(validateChatProductId(0)).toEqual({ ok: false, reason: "out_of_range" });
    expect(validateChatProductId(-1)).toEqual({ ok: false, reason: "out_of_range" });
    expect(validateChatProductId(9007199254740992)).toEqual({ ok: false, reason: "out_of_range" });
    expect(validateChatProductId("1")).toEqual({ ok: false, reason: "format" });
    expect(validateChatProductId(1.5)).toEqual({ ok: false, reason: "format" });
    expect(validateChatProductId(Number.NaN)).toEqual({ ok: false, reason: "format" });
  });

  it("本文: 許可したキー以外は落とし、message は前後の空白を除いた値で返す。違反は fields にまとめる", () => {
    expect(validateChatRequestBody({ message: " 送料は？ ", product_id: 3, admin: true })).toEqual({
      ok: true,
      payload: { message: "送料は？", product_id: 3 },
    });
    expect(validateChatRequestBody({ message: "a" })).toEqual({ ok: true, payload: { message: "a", product_id: null } });
    expect(validateChatRequestBody({ message: "", product_id: 0 })).toEqual({
      ok: false,
      fields: [
        { name: "message", reason: "required" },
        { name: "product_id", reason: "out_of_range" },
      ],
    });
  });
});
