import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import CategoryNav from "@/components/CategoryNav";
import type { Category } from "@/lib/types";

// 商品一覧 DS-SCR-002 のカテゴリ導線。ALL（性別なし）で子カテゴリを kind ごとに 1 枚へまとめる不具合修正。
// カテゴリは性別ごとに別の行（women-tops・men-tops・kids-teen-tops）。ALL で slug 先頭の 1 枚へリンクすると
// 女性物しか出なかったため、ALL では `?kind=` で性別をまたいで絞る。
const CATEGORIES: Category[] = [
  {
    slug: "women",
    name: "レディース",
    gender: "women",
    children: [
      { slug: "women-tops", name: "トップス", kind: "tops", product_count: 3 },
      { slug: "women-bottoms", name: "ボトムス", kind: "bottoms", product_count: 3 },
      { slug: "women-dresses", name: "ワンピース", kind: "dresses", product_count: 2 },
    ],
  },
  {
    slug: "men",
    name: "メンズ",
    gender: "men",
    children: [
      { slug: "men-tops", name: "トップス", kind: "tops", product_count: 4 },
      { slug: "men-bottoms", name: "ボトムス", kind: "bottoms", product_count: 3 },
    ],
  },
  {
    slug: "kids-teen",
    name: "キッズ・ティーン",
    gender: "kids_teen",
    children: [
      { slug: "kids-teen-tops", name: "トップス（キッズ）", kind: "tops", product_count: 3 },
      { slug: "kids-teen-outer", name: "アウター", kind: "outer", product_count: 1 },
    ],
  },
];

function childList() {
  return screen.getByRole("list", { name: "商品カテゴリ" });
}

describe("CategoryNav: ALL（性別なし）", () => {
  it("同じ種類は 1 枚にまとまり、並びは最初に出てきた順（トップス → ボトムス → ワンピース → アウター）", () => {
    render(<CategoryNav categories={CATEGORIES} />);
    const links = within(childList()).getAllByRole("link");
    expect(links.map((a) => a.textContent)).toEqual(["トップス10", "ボトムス6", "ワンピース2", "アウター1"]);
    // 「トップス」の札が 3 枚並ぶことはない
    expect(within(childList()).getAllByRole("link", { name: /^トップス/ })).toHaveLength(1);
  });

  it("表示名は最初に出てきた名前、件数は全性別の合計（3 + 4 + 3 = 10）", () => {
    render(<CategoryNav categories={CATEGORIES} />);
    const tops = within(childList()).getByRole("link", { name: "トップス10" });
    expect(tops).toBeInTheDocument();
    expect(within(childList()).queryByText("トップス（キッズ）")).not.toBeInTheDocument();
    expect(within(childList()).getByRole("link", { name: "ボトムス6" })).toBeInTheDocument();
  });

  it("リンク先は `/products?kind=<kind>`（gender・category は付かない）", () => {
    render(<CategoryNav categories={CATEGORIES} />);
    const list = childList();
    expect(within(list).getByRole("link", { name: "トップス10" })).toHaveAttribute("href", "/products?kind=tops");
    expect(within(list).getByRole("link", { name: "ボトムス6" })).toHaveAttribute("href", "/products?kind=bottoms");
    expect(within(list).getByRole("link", { name: "アウター1" })).toHaveAttribute("href", "/products?kind=outer");
    for (const a of within(list).getAllByRole("link")) {
      expect(a.getAttribute("href")).not.toMatch(/category=|gender=/);
    }
  });

  it("選択中は URL の kind で判定する（aria-current=page）。ALL タブも選択中のまま", () => {
    render(<CategoryNav categories={CATEGORIES} kind="bottoms" />);
    const list = childList();
    expect(within(list).getByRole("link", { name: "ボトムス6" })).toHaveAttribute("aria-current", "page");
    expect(within(list).getByRole("link", { name: "トップス10" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "ALL" })).toHaveAttribute("aria-current", "page");
  });

  it("kind が無い URL では選択中の札は無い（category の slug では判定しない）", () => {
    render(<CategoryNav categories={CATEGORIES} category="men-tops" />);
    for (const a of within(childList()).getAllByRole("link")) {
      expect(a).not.toHaveAttribute("aria-current");
    }
  });

  it("kind が null の子は束ねず、slug の category リンクで 1 枚ずつ出す", () => {
    const cats: Category[] = [
      { slug: "women", name: "レディース", gender: "women", children: [{ slug: "women-misc", name: "その他", kind: null, product_count: 1 }] },
      { slug: "men", name: "メンズ", gender: "men", children: [{ slug: "men-misc", name: "その他", kind: null, product_count: 2 }] },
    ];
    render(<CategoryNav categories={cats} />);
    const links = within(childList()).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/products?category=women-misc", "/products?category=men-misc"]);
  });

  it("categories=null（取得失敗）なら性別タブだけで、子カテゴリのリストは出ない", () => {
    render(<CategoryNav categories={null} />);
    expect(screen.getByRole("link", { name: "ALL" })).toHaveAttribute("href", "/products");
    expect(screen.queryByRole("list", { name: "商品カテゴリ" })).not.toBeInTheDocument();
  });
});

describe("CategoryNav: 性別を選択中（従来どおり）", () => {
  it("その性別の子カテゴリを 1 枚ずつ。リンクは `?gender=&category=<slug>`、件数はその性別の分だけ", () => {
    render(<CategoryNav categories={CATEGORIES} gender="men" />);
    const list = childList();
    const links = within(list).getAllByRole("link");
    expect(links.map((a) => a.textContent)).toEqual(["トップス4", "ボトムス3"]);
    expect(within(list).getByRole("link", { name: "トップス4" })).toHaveAttribute("href", "/products?gender=men&category=men-tops");
    expect(within(list).getByRole("link", { name: "ボトムス3" })).toHaveAttribute("href", "/products?gender=men&category=men-bottoms");
  });

  it("選択中は URL の category（slug）で判定する。kind は見ない", () => {
    render(<CategoryNav categories={CATEGORIES} gender="women" category="women-bottoms" kind="tops" />);
    const list = childList();
    expect(within(list).getByRole("link", { name: "ボトムス3" })).toHaveAttribute("aria-current", "page");
    expect(within(list).getByRole("link", { name: "トップス3" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "WOMEN" })).toHaveAttribute("aria-current", "page");
  });

  it("kids_teen でも同じ（kids-teen の子だけ並ぶ）", () => {
    render(<CategoryNav categories={CATEGORIES} gender="kids_teen" />);
    const list = childList();
    expect(within(list).getByRole("link", { name: "トップス（キッズ）3" })).toHaveAttribute(
      "href",
      "/products?gender=kids_teen&category=kids-teen-tops",
    );
    expect(within(list).getAllByRole("link")).toHaveLength(2);
  });
});
