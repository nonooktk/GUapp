import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AdminOrderFilters from "@/components/admin/AdminOrderFilters";
import AdminOrderTable from "@/components/admin/AdminOrderTable";
import AdminProductFilters from "@/components/admin/AdminProductFilters";
import AdminProductTable from "@/components/admin/AdminProductTable";
import { parseOrderQuery, parseProductQuery } from "@/lib/admin-query";
import { makeAdminOrderListItem } from "./helpers/admin";

// AT-31〜33・ST-SEC-87 の画面部品（一覧の表と検索フォーム）。UT-WEB-43・46 の検索条件を画面に結ぶ部分

describe("商品一覧の表（DS-SCR-015-1）", () => {
  const items = [
    { product_id: 1, name: "スムースコットンT", price_incl_tax: 1990, published: true, variant_count: 4, total_stock: 120, out_of_stock_variants: 0 },
    { product_id: 29, name: "リブレギンス", price_incl_tax: 990, published: false, variant_count: 2, total_stock: 0, out_of_stock_variants: 2 },
  ];

  it("行ごとに ID・商品名・税込価格・公開・在庫計・在庫0のSKU数・編集リンク。非公開は灰色のバッジ、在庫 0 の SKU がある行は強調", () => {
    render(<AdminProductTable items={items} />);
    const rows = screen.getAllByTestId("admin-product-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("スムースコットンT");
    expect(rows[0]).toHaveTextContent("¥1,990");
    expect(within(rows[0]).queryByTestId("admin-private-badge")).toBeNull();
    expect(within(rows[1]).getByTestId("admin-private-badge")).toHaveTextContent("非公開");
    expect(within(rows[0]).getByTestId("admin-out-of-stock").className).not.toContain("text-danger");
    expect(within(rows[1]).getByTestId("admin-out-of-stock").className).toContain("text-danger");
    expect(within(rows[1]).getByRole("link", { name: "リブレギンスを編集" })).toHaveAttribute("href", "/admin/products/29");
  });

  it("商品名に HTML があっても文字列として表示する(ST-SEC-87)", () => {
    const evil = `<img src=x onerror=alert(1)><script>alert(1)</script>`;
    const { container } = render(<AdminProductTable items={[{ ...items[0], name: evil }]} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText(evil)).toBeInTheDocument();
  });

  it("0 件は「条件に合う商品はありません」", () => {
    render(<AdminProductTable items={[]} />);
    expect(screen.getByTestId("admin-products-empty")).toBeInTheDocument();
  });
});

describe("商品の検索フォーム", () => {
  it("GET フォームで /admin/products に送る(検索条件は URL のクエリ)。検査済みの値を戻す", () => {
    const query = parseProductQuery({ q: "T", visibility: "private", stock: "out" });
    render(<AdminProductFilters query={query} />);
    const form = screen.getByRole("form", { name: "商品の検索" });
    expect(form).toHaveAttribute("method", "get");
    expect(form).toHaveAttribute("action", "/admin/products");
    expect(screen.getByLabelText(/キーワード/)).toHaveValue("T");
    expect(screen.getByLabelText(/キーワード/)).toHaveAttribute("name", "q");
    expect(screen.getByLabelText("公開状態")).toHaveValue("private");
    expect(screen.getByLabelText("在庫")).toHaveValue("out");
    expect(screen.queryByRole("textbox", { name: /page/i })).toBeNull();
  });

  it("列挙外の値は既定(すべて)に戻して表示する", () => {
    render(<AdminProductFilters query={parseProductQuery({ visibility: "x", stock: "y" })} />);
    expect(screen.getByLabelText("公開状態")).toHaveValue("all");
    expect(screen.getByLabelText("在庫")).toHaveValue("all");
  });
});

describe("注文一覧の表（DS-SCR-015-3）", () => {
  it("注文番号(詳細へのリンク)・JST の日時・状態・受取・合計・点数・マスクしたメール。氏名・電話・住所の列がない", () => {
    render(<AdminOrderTable items={[makeAdminOrderListItem(), makeAdminOrderListItem({ order_number: "GU-261025-ZZZZZZZZ", receive_method: "store", customer_type: "member" })]} />);
    const rows = screen.getAllByTestId("admin-order-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("link", { name: "GU-261024-ABCDEFGH" })).toHaveAttribute("href", "/admin/orders/GU-261024-ABCDEFGH");
    expect(rows[0]).toHaveTextContent("2026/10/24 10:15"); // UTC 01:15 → JST 10:15
    expect(rows[0]).toHaveTextContent("受付済");
    expect(rows[0]).toHaveTextContent("配送");
    expect(rows[0]).toHaveTextContent("¥3,980");
    expect(rows[0]).toHaveTextContent("t***@example.com");
    expect(rows[0]).toHaveTextContent("ゲスト");
    expect(rows[1]).toHaveTextContent("店舗受け取り");
    expect(rows[1]).toHaveTextContent("会員");
    const heads = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toEqual(["注文番号", "注文日時（JST）", "状態", "受取", "合計", "点数", "連絡先"]);
  });

  it("0 件は「条件に合う注文はありません」", () => {
    render(<AdminOrderTable items={[]} />);
    expect(screen.getByTestId("admin-orders-empty")).toBeInTheDocument();
  });
});

describe("注文の検索フォーム", () => {
  it("GET フォームで /admin/orders に送る。期間は type=date。状態は 8 値 + すべて", () => {
    render(<AdminOrderFilters query={parseOrderQuery({ status: "shipped", from: "2026-10-01", to: "2026-10-31", order_number: "gu-261024-abcdefgh", email: "A@Example.com" })} />);
    const form = screen.getByRole("form", { name: "注文の検索" });
    expect(form).toHaveAttribute("method", "get");
    expect(form).toHaveAttribute("action", "/admin/orders");
    expect(screen.getByLabelText("期間（開始）")).toHaveAttribute("type", "date");
    expect(screen.getByLabelText("期間（開始）")).toHaveValue("2026-10-01");
    expect(screen.getByLabelText("期間（終了）")).toHaveValue("2026-10-31");
    expect(screen.getByLabelText("状態")).toHaveValue("shipped");
    expect(within(screen.getByLabelText("状態")).getAllByRole("option")).toHaveLength(9);
    expect(screen.getByLabelText(/注文番号/)).toHaveAttribute("name", "order_number");
    expect(screen.getByLabelText(/メール/)).toHaveAttribute("name", "email");
  });

  it("形が違う入力は項目の下にエラーを出し、入力は残す。API 側のエラー文言はフォームに出す", () => {
    render(<AdminOrderFilters query={parseOrderQuery({ from: "2026-02-30", order_number: "bad", email: "x" })} apiError="期間は 366 日以内で指定してください" />);
    const alerts = screen.getAllByRole("alert").map((a) => a.textContent);
    expect(alerts).toContain("日付は YYYY-MM-DD の形で、実在する日付を入力してください");
    expect(alerts).toContain("注文番号の形式が正しくありません（例：GU-261024-ABCDEFGH）");
    expect(alerts).toContain("メールアドレスの形式が正しくありません");
    expect(screen.getByTestId("admin-orders-api-error")).toHaveTextContent("366 日以内");
    expect(screen.getByLabelText(/注文番号/)).toHaveValue("bad");
  });
});
