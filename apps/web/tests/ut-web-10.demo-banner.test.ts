import { describe, expect, it, vi } from "vitest";
import { parseDemoPublicUntil } from "@/lib/demo-banner";

// テスト設計書 UT-WEB-10: 期間限定バナーの終了日パース（公開追補 設計仕様書 6 章・DS-DEC-50）
// DEMO_PUBLIC_UNTIL は実行時の環境変数（NEXT_PUBLIC_ は使わない）。未設定なら帯を出さない。
// 形式が不正なら帯を出さずログに警告。表示は YYYY/MM/DD。

describe("UT-WEB-10 parseDemoPublicUntil", () => {
  it("未設定（undefined）は null", () => {
    expect(parseDemoPublicUntil(undefined)).toBeNull();
  });

  it("空文字は null", () => {
    expect(parseDemoPublicUntil("")).toBeNull();
  });

  it("空白のみは null", () => {
    expect(parseDemoPublicUntil("   ")).toBeNull();
  });

  it("YYYY-MM-DD 形式は YYYY/MM/DD に変換する", () => {
    expect(parseDemoPublicUntil("2026-10-09")).toBe("2026/10/09");
  });

  it("前後空白はトリムしてから解釈する", () => {
    expect(parseDemoPublicUntil("  2026-10-09  ")).toBe("2026/10/09");
  });

  it("区切りが / など YYYY-MM-DD でない形式は null で警告する", () => {
    const warn = vi.fn();
    expect(parseDemoPublicUntil("2026/10/09", warn)).toBeNull();
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it("実在しない日付（例: 13月・32日）は null で警告する", () => {
    const warn = vi.fn();
    expect(parseDemoPublicUntil("2026-13-01", warn)).toBeNull();
    expect(warn).toHaveBeenCalledTimes(1);
    const warn2 = vi.fn();
    expect(parseDemoPublicUntil("2026-01-32", warn2)).toBeNull();
    expect(warn2).toHaveBeenCalledTimes(1);
  });

  it("桁数が違う（例: 26-10-09）は null で警告する", () => {
    const warn = vi.fn();
    expect(parseDemoPublicUntil("26-10-09", warn)).toBeNull();
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it("うるう年 2/29 は許可する（2028 年はうるう年）", () => {
    expect(parseDemoPublicUntil("2028-02-29")).toBe("2028/02/29");
  });

  it("うるう年でない年の 2/29 は null で警告する", () => {
    const warn = vi.fn();
    expect(parseDemoPublicUntil("2026-02-29", warn)).toBeNull();
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it("未設定・空文字では警告しない", () => {
    const warn = vi.fn();
    parseDemoPublicUntil(undefined, warn);
    parseDemoPublicUntil("", warn);
    expect(warn).not.toHaveBeenCalled();
  });
});
