import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Header from "@/components/Header";

// テスト設計書 UT-WEB-01（カート点数バッジ）の土台。設計仕様書 6.2 共通レイアウト
describe("UT-WEB-01 Header", () => {
  it("props の点数がバッジに表示される", () => {
    render(<Header cartCount={3} />);
    expect(screen.getByTestId("cart-count-badge")).toHaveTextContent("3");
    expect(screen.getByRole("link", { name: "カート（3点）" })).toBeInTheDocument();
  });

  it("点数 0 のときはバッジを描画しない", () => {
    render(<Header cartCount={0} />);
    expect(screen.queryByTestId("cart-count-badge")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "カート（0点）" })).toBeInTheDocument();
  });

  it("100 点以上は 99+ と表示する", () => {
    render(<Header cartCount={120} />);
    expect(screen.getByTestId("cart-count-badge")).toHaveTextContent("99+");
  });

  it("メニューボタン・ロゴ・検索・お気に入り・会員がアクセシブル名付きで存在する", () => {
    render(<Header cartCount={0} />);
    expect(screen.getByRole("button", { name: "メニューを開く" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "GU ホーム" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "検索" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "お気に入り" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "会員" })).toBeInTheDocument();
  });
});
