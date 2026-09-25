import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DemoPeriodBanner from "@/components/DemoPeriodBanner";

// テスト設計書 UT-WEB-10: 期間限定バナー表示（公開追補 設計仕様書 6 章・DS-DEC-50）
// 375px でも読める・色だけで意味を伝えない（文言で明示）という基準を満たすかを確認する。
describe("DemoPeriodBanner（公開追補 6 章）", () => {
  it("untilDisplay が null なら何も描画しない", () => {
    const { container } = render(<DemoPeriodBanner untilDisplay={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("untilDisplay があれば終了日を含む文言を描画する", () => {
    render(<DemoPeriodBanner untilDisplay="2026/10/09" />);
    expect(
      screen.getByText("講義レビュー用のデモとして、2026/10/09 まで期間限定で公開しています"),
    ).toBeInTheDocument();
  });

  it("色だけに頼らない（テキストで明示。役割は status で補助する）", () => {
    render(<DemoPeriodBanner untilDisplay="2026/10/09" />);
    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent("期間限定で公開しています");
  });
});
