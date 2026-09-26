import { describe, expect, it } from "vitest";
import { formatJst, formatJstDate } from "@/lib/datetime";

// 完了画面の `ordered_at`（UTC）→ JST 表示（設計仕様書 6.8）
describe("formatJst", () => {
  it("UTC の ISO を Asia/Tokyo（+9 時間）の `YYYY/MM/DD HH:mm` にする", () => {
    expect(formatJst("2026-09-18T03:04:05Z")).toBe("2026/09/18 12:04");
    expect(formatJst("2026-09-18T15:30:00+00:00")).toBe("2026/09/19 00:30"); // 日付をまたぐ
  });

  it("タイムゾーンの無い文字列は UTC と見なす。壊れた値は空文字", () => {
    expect(formatJst("2026-09-18T03:04:05")).toBe("2026/09/18 12:04");
    expect(formatJst("not a date")).toBe("");
    expect(formatJst("")).toBe("");
  });
});

// P2-a コンテンツ・お知らせ一覧の日付表示（設計仕様書 P2 追補a 6.3。DS-DEC-40: 表示は JST）
describe("formatJstDate", () => {
  it("UTC の ISO を Asia/Tokyo の `YYYY-MM-DD` にする（時刻は含めない）", () => {
    expect(formatJstDate("2026-09-18T03:04:05Z")).toBe("2026-09-18");
    expect(formatJstDate("2026-09-18T15:30:00+00:00")).toBe("2026-09-19"); // 日付をまたぐ
  });

  it("タイムゾーンの無い文字列は UTC と見なす。壊れた値は空文字", () => {
    expect(formatJstDate("2026-09-18T03:04:05")).toBe("2026-09-18");
    expect(formatJstDate("not a date")).toBe("");
    expect(formatJstDate("")).toBe("");
  });
});
