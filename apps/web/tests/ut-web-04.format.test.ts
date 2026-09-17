import { describe, expect, it } from "vitest";
import { formatNumber, formatYen, YEN_SIGN } from "@/lib/format";

// テスト設計書 UT-WEB-04: 金額表示は半角 ¥（U+00A5）＋ 3 桁区切り。プラン 4.4 の Wave 1 完了条件
describe("UT-WEB-04 formatYen", () => {
  it("6520 → ¥6,520", () => {
    expect(formatYen(6520)).toBe("¥6,520");
  });

  it("先頭の通貨記号は半角 ¥（U+00A5）。全角 ￥（U+FFE5）ではない", () => {
    const s = formatYen(6520);
    expect(s.charCodeAt(0)).toBe(0xa5);
    expect(YEN_SIGN.charCodeAt(0)).toBe(0xa5);
    expect(s).not.toContain("￥");
  });

  it("0 → ¥0", () => {
    expect(formatYen(0)).toBe("¥0");
  });

  it("1234567 → ¥1,234,567", () => {
    expect(formatYen(1234567)).toBe("¥1,234,567");
  });

  it("小数は切り捨て、負数は - を前に付ける", () => {
    expect(formatYen(1990.9)).toBe("¥1,990");
    expect(formatYen(-550)).toBe("-¥550");
  });

  it("NaN・Infinity は ¥0 に丸める（表示を壊さない）", () => {
    expect(formatYen(Number.NaN)).toBe("¥0");
    expect(formatYen(Number.POSITIVE_INFINITY)).toBe("¥0");
  });

  it("formatNumber は記号なしの 3 桁区切り（送料無料の閾値表示用）", () => {
    expect(formatNumber(4990)).toBe("4,990");
  });
});
