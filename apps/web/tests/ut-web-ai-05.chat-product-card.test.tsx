import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ChatProductCard from "@/components/chat/ChatProductCard";
import { IMAGE_BASE, PRODUCT } from "./helpers/chat";

// テスト設計書 UT-WEB-AI-05: 商品カードは api の DB の値だけで描く。LLM の文章（reason）は HTML として解釈しない。
// 設計仕様書 P2 追補d 6.2・7.1。

describe("UT-WEB-AI-05 ChatProductCard", () => {
  it("リンクは /products/{id}、価格は formatYen の整形（¥2,990）、画像の alt は商品名、理由を表示する", () => {
    render(<ChatProductCard product={PRODUCT} imageBaseUrl={IMAGE_BASE} />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/products/12");
    expect(screen.getByText("¥2,990")).toBeInTheDocument();
    expect(screen.getByText("（税込）")).toBeInTheDocument();
    const img = screen.getByAltText("薄手パーカー");
    expect(img).toHaveAttribute("src", "http://img.test/products/012/1.png");
    expect(screen.getByText("薄手で重ね着しやすいためです。")).toBeInTheDocument();
    expect(screen.queryByText("在庫切れ")).not.toBeInTheDocument();
  });

  it("sold_out は在庫切れのバッジを出し、価格は出さない", () => {
    render(<ChatProductCard product={{ ...PRODUCT, sold_out: true }} imageBaseUrl={IMAGE_BASE} />);
    expect(screen.getAllByText("在庫切れ").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("¥2,990")).not.toBeInTheDocument();
  });

  it("画像が無くても壊れず、NO IMAGE の枠を出す", () => {
    render(<ChatProductCard product={{ ...PRODUCT, image_path: null }} imageBaseUrl={IMAGE_BASE} />);
    expect(screen.getByLabelText("薄手パーカー（画像なし）")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("reason・名前の HTML は文字として表示され、script や b の要素にならない", () => {
    const { container } = render(
      <ChatProductCard
        product={{ ...PRODUCT, name: "<b>x</b>", reason: "<script>alert(1)</script>" }}
        imageBaseUrl={IMAGE_BASE}
      />,
    );
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
    expect(screen.getByText("<b>x</b>")).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });

  it("価格は API の price_incl_tax をそのまま整形する（LLM の文章に価格があっても使わない）", () => {
    render(<ChatProductCard product={{ ...PRODUCT, price_incl_tax: 1490, reason: "税込 1 円です" }} imageBaseUrl={IMAGE_BASE} />);
    expect(screen.getByText("¥1,490")).toBeInTheDocument();
    expect(screen.queryByText("¥1")).not.toBeInTheDocument();
  });
});
