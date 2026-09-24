import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Header from "@/components/Header";
import type { Category } from "@/lib/types";

// テスト設計書 AT-07（オールメニューのカテゴリから商品一覧へ遷移）・設計仕様書 6.2 U-06・デザイン基準 v1 6 章（キーボード操作）
const CATEGORIES: Category[] = [
  {
    slug: "women",
    name: "レディース",
    gender: "women",
    children: [
      { slug: "women-tops", name: "トップス", product_count: 3 },
      { slug: "women-bottoms", name: "ボトムス", product_count: 2 },
    ],
  },
  {
    slug: "men",
    name: "メンズ",
    gender: "men",
    children: [{ slug: "men-tops", name: "トップス", product_count: 4 }],
  },
  {
    slug: "kids-teen",
    name: "キッズ・ティーン",
    gender: "kids_teen",
    children: [{ slug: "kids-teen-outer", name: "アウター", product_count: 1 }],
  },
];

function openMenu() {
  const button = screen.getByRole("button", { name: "メニューを開く" });
  fireEvent.click(button);
  return button;
}

describe("AT-07 オールメニュー（Header + AllMenu）", () => {
  it("初期状態は閉じていて aria-expanded=false、ダイアログは無い", () => {
    render(<Header cartCount={0} categories={CATEGORIES} />);
    const button = screen.getByRole("button", { name: "メニューを開く" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveAttribute("aria-haspopup", "dialog");
    expect(button).toHaveAttribute("aria-controls");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("≡ を押すと開いて aria-expanded=true、aria-controls がダイアログを指し、閉じるボタンにフォーカスが移る", () => {
    render(<Header cartCount={0} categories={CATEGORIES} />);
    const button = openMenu();
    expect(button).toHaveAttribute("aria-expanded", "true");
    const dialog = screen.getByRole("dialog", { name: "メニュー" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog.id).toBe(button.getAttribute("aria-controls"));
    const close = screen.getByRole("button", { name: "メニューを閉じる" });
    expect(close).toHaveFocus();
  });

  it("閉じるボタンで閉じ、aria-expanded=false に戻り、≡ にフォーカスが戻る", () => {
    render(<Header cartCount={0} categories={CATEGORIES} />);
    const button = openMenu();
    fireEvent.click(screen.getByRole("button", { name: "メニューを閉じる" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
  });

  it("Escape で閉じる", () => {
    render(<Header cartCount={0} categories={CATEGORIES} />);
    const button = openMenu();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
  });

  it("背景（オーバーレイ）クリックで閉じ、パネル内クリックでは閉じない", () => {
    render(<Header cartCount={0} categories={CATEGORIES} />);
    openMenu();
    fireEvent.click(screen.getByRole("dialog"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("all-menu-overlay"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("性別 3 区分と子カテゴリのリンク href が正しく、件数が添えられる", () => {
    render(<Header cartCount={0} categories={CATEGORIES} />);
    openMenu();
    const nav = screen.getByRole("navigation", { name: "オールメニュー" });
    expect(within(nav).getByRole("link", { name: "WOMEN" })).toHaveAttribute("href", "/products?gender=women");
    expect(within(nav).getByRole("link", { name: "MEN" })).toHaveAttribute("href", "/products?gender=men");
    expect(within(nav).getByRole("link", { name: "KIDS・TEEN" })).toHaveAttribute("href", "/products?gender=kids_teen");

    const women = within(nav).getByRole("list", { name: "WOMEN のカテゴリ" });
    expect(within(women).getByRole("link", { name: "トップス 3" })).toHaveAttribute(
      "href",
      "/products?gender=women&category=women-tops",
    );
    expect(within(women).getByRole("link", { name: "ボトムス 2" })).toHaveAttribute(
      "href",
      "/products?gender=women&category=women-bottoms",
    );
    const men = within(nav).getByRole("list", { name: "MEN のカテゴリ" });
    expect(within(men).getByRole("link", { name: "トップス 4" })).toHaveAttribute("href", "/products?gender=men&category=men-tops");
    const kids = within(nav).getByRole("list", { name: "KIDS・TEEN のカテゴリ" });
    expect(within(kids).getByRole("link", { name: "アウター 1" })).toHaveAttribute(
      "href",
      "/products?gender=kids_teen&category=kids-teen-outer",
    );

    // P2 のテキストリンクは # のまま
    expect(within(nav).getByRole("link", { name: "お知らせ P2" })).toHaveAttribute("href", "#");
  });

  it("リンクを選ぶとメニューが閉じる", () => {
    render(<Header cartCount={0} categories={CATEGORIES} />);
    const button = openMenu();
    fireEvent.click(screen.getByRole("link", { name: "トップス 3" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("categories=null（取得失敗）でも開けて、性別リンクと『読み込めませんでした』を出す", () => {
    render(<Header cartCount={0} categories={null} />);
    openMenu();
    const nav = screen.getByRole("navigation", { name: "オールメニュー" });
    expect(within(nav).getByRole("link", { name: "WOMEN" })).toHaveAttribute("href", "/products?gender=women");
    expect(within(nav).queryByRole("list", { name: "WOMEN のカテゴリ" })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("カテゴリを読み込めませんでした。");
  });

  it("Tab はパネル内で循環する（最後 → 最初、Shift+Tab で最初 → 最後）", () => {
    render(<Header cartCount={0} categories={CATEGORIES} />);
    openMenu();
    const dialog = screen.getByRole("dialog");
    const close = screen.getByRole("button", { name: "メニューを閉じる" });
    const last = screen.getByRole("link", { name: "INFO P2" });
    last.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });
});
