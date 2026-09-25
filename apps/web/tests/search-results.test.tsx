import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SearchResults from "@/components/SearchResults";
import type { ProductSummary, SearchResponse } from "@/lib/types";

// DS-SCR-002 検索モード（設計仕様書 P2 追補a 6.2）。AT-09（結果表示）・AT-10（0 件時の代替導線）の土台。

vi.mock("@/lib/client/search-api", () => ({
  fetchSearchPage: vi.fn(),
}));
import { fetchSearchPage } from "@/lib/client/search-api";

const item = (id: number, name: string): ProductSummary => ({
  id,
  name,
  price_incl_tax: 1990,
  image_path: null,
  colors: ["黒"],
  sold_out: false,
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("SearchResults 一覧表示・もっと見る", () => {
  it("初期件数を描画し、hasMore なら「もっと見る」を出す", () => {
    render(
      <SearchResults
        query="シャツ"
        initialItems={[item(1, "オーバーサイズシャツ")]}
        initialPage={1}
        hasMore={true}
        total={3}
        similarKeywords={[]}
        recommendedCategories={[]}
        imageBaseUrl="http://localhost:3000"
      />,
    );
    expect(screen.getByRole("list", { name: "検索結果" })).toBeInTheDocument();
    expect(screen.getByText("オーバーサイズシャツ")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "もっと見る" })).toBeInTheDocument();
  });

  it("「もっと見る」で次ページを取得し、重複を除いて末尾に追加する", async () => {
    const next: SearchResponse = {
      query: "シャツ",
      items: [item(1, "オーバーサイズシャツ"), item(2, "オックスフォードシャツ")],
      page: 2,
      per_page: 24,
      total: 2,
      has_more: false,
      similar_keywords: [],
      recommended_categories: [],
    };
    vi.mocked(fetchSearchPage).mockResolvedValue(next);

    render(
      <SearchResults
        query="シャツ"
        initialItems={[item(1, "オーバーサイズシャツ")]}
        initialPage={1}
        hasMore={true}
        total={2}
        similarKeywords={[]}
        recommendedCategories={[]}
        imageBaseUrl="http://localhost:3000"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "もっと見る" }));

    await waitFor(() => expect(screen.getByText("オックスフォードシャツ")).toBeInTheDocument());
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "もっと見る" })).not.toBeInTheDocument();
    expect(fetchSearchPage).toHaveBeenCalledWith("シャツ", 2);
  });
});

describe("SearchResults 0 件時の代替導線（AT-10・ST-F003-06）", () => {
  it("類似キーワード・おすすめカテゴリへのリンクを出す", () => {
    render(
      <SearchResults
        query="ｽﾆｰｶｰ"
        initialItems={[]}
        initialPage={1}
        hasMore={false}
        total={0}
        similarKeywords={["ジーンズ"]}
        recommendedCategories={[
          { slug: "men-tops", name: "トップス", product_count: 4 },
          { slug: "women-tops", name: "トップス", product_count: 3 },
        ]}
        imageBaseUrl="http://localhost:3000"
      />,
    );
    expect(screen.getByText("該当する商品が見つかりませんでした。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ジーンズ" })).toHaveAttribute("href", "/search?q=%E3%82%B8%E3%83%BC%E3%83%B3%E3%82%BA");
    const categoryLink = screen.getAllByRole("link", { name: /トップス/ })[0];
    expect(categoryLink).toHaveAttribute("href", "/products?category=men-tops");
  });

  it("similar_keywords が空配列のときは「もしかして」の見出し自体を描画しない（デザイン基準 6 章）", () => {
    render(
      <SearchResults
        query="ｽﾆｰｶｰ"
        initialItems={[]}
        initialPage={1}
        hasMore={false}
        total={0}
        similarKeywords={[]}
        recommendedCategories={[{ slug: "men-tops", name: "トップス", product_count: 4 }]}
        imageBaseUrl="http://localhost:3000"
      />,
    );
    expect(screen.queryByText("もしかして")).not.toBeInTheDocument();
    expect(screen.getByText("おすすめのカテゴリ")).toBeInTheDocument();
  });

  it("検索語に HTML 風の文字列が含まれても、タグとして解釈されず文字どおり表示される（dangerouslySetInnerHTML 不使用）", () => {
    render(
      <SearchResults
        query="a"
        initialItems={[]}
        initialPage={1}
        hasMore={false}
        total={0}
        similarKeywords={["<script>alert(1)</script>"]}
        recommendedCategories={[]}
        imageBaseUrl="http://localhost:3000"
      />,
    );
    const link = screen.getByRole("link", { name: "<script>alert(1)</script>" });
    // textContent はブラウザが実体参照をデコードして返すため元の文字列と一致するが、
    // 実際の DOM（innerHTML）はエスケープ済みでタグとして解釈されていないことを確認する
    expect(link.textContent).toBe("<script>alert(1)</script>");
    expect(link.innerHTML).toBe("&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(link.querySelector("script")).toBeNull();
  });
});
