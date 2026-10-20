import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import OrderDetail, { DELIVERY_STEPS, progressSteps, STORE_STEPS } from "@/components/OrderDetail";
import OrderHistoryList, { firstItemLabel, pageHref } from "@/components/OrderHistoryList";
import type { OrderHistoryItem, OrderHistoryResponse, OrderStatus } from "@/lib/types";
import { makeOrder, STORE_PATCH } from "./helpers/fixtures";

// テスト設計書 UT-WEB-22（注文履歴の一覧・詳細。DS-SCR-008・009）。設計仕様書 6.4・6.5・DS-PRC-024a・AT-14・ST-SEC-54

function item(patch: Partial<OrderHistoryItem> = {}): OrderHistoryItem {
  return {
    order_number: "GU-261024-ABCDEFGH",
    status: "accepted",
    status_label: "受付済",
    ordered_at: "2026-10-24T01:15:00Z",
    total: 4530,
    receive_method: "store",
    item_count: 3,
    first_item_name: "スムースコットンT",
    ...patch,
  };
}
const history = (patch: Partial<OrderHistoryResponse> = {}): OrderHistoryResponse => ({
  items: [item()],
  page: 1,
  per_page: 10,
  total: 1,
  has_more: false,
  ...patch,
});

describe("UT-WEB-22 注文履歴の一覧", () => {
  it("0 件: 「まだご注文がありません」とホームへのリンク", () => {
    render(<OrderHistoryList history={history({ items: [], total: 0 })} />);
    expect(screen.getByTestId("history-empty")).toHaveTextContent("まだご注文がありません");
    expect(screen.getByRole("link", { name: "ホームへ" })).toHaveAttribute("href", "/");
  });

  it("1 件: 注文日（JST）・注文番号・状態名・商品名・受け取り方法・合計が出て、詳細へのリンク", () => {
    render(<OrderHistoryList history={history({ items: [item({ item_count: 1, receive_method: "delivery" })] })} />);
    expect(screen.getByRole("heading", { name: "ご注文履歴（全 1 件）" })).toBeInTheDocument();
    const link = screen.getByTestId("history-item");
    expect(link).toHaveAttribute("href", "/mypage/orders/GU-261024-ABCDEFGH");
    expect(link).toHaveTextContent("2026/10/24");
    expect(link).toHaveTextContent("GU-261024-ABCDEFGH");
    expect(link).toHaveTextContent("受付済");
    expect(link).toHaveTextContent("スムースコットンT");
    expect(link).not.toHaveTextContent("ほか");
    expect(link).toHaveTextContent("配送");
    expect(link).toHaveTextContent("¥4,530");
  });

  it("「ほか N 点」は item_count - 1（1 点なら付かない）", () => {
    expect(firstItemLabel("商品A", 1)).toBe("商品A");
    expect(firstItemLabel("商品A", 3)).toBe("商品Aほか 2 点");
    render(<OrderHistoryList history={history({ items: [item({ item_count: 3 })] })} />);
    expect(screen.getByTestId("history-item")).toHaveTextContent("スムースコットンTほか 2 点");
    expect(screen.getByTestId("history-item")).toHaveTextContent("店舗受け取り");
  });

  it("複数件を並べる。ページ送り: 1 ページ目は「次へ」だけ、2 ページ目は「前へ」（has_more=false なら次へなし）", () => {
    const items = [item(), item({ order_number: "GU-261023-ZZZZ2222" })];
    const { unmount } = render(<OrderHistoryList history={history({ items, total: 12, has_more: true })} />);
    expect(screen.getAllByTestId("history-item")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "次へ" })).toHaveAttribute("href", "/mypage?page=2");
    expect(screen.queryByRole("link", { name: "前へ" })).not.toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    unmount();

    render(<OrderHistoryList history={history({ items, page: 2, total: 12, has_more: false })} />);
    expect(screen.getByRole("link", { name: "前へ" })).toHaveAttribute("href", "/mypage");
    expect(screen.queryByRole("link", { name: "次へ" })).not.toBeInTheDocument();
    expect(pageHref(3)).toBe("/mypage?page=3");
  });

  it("範囲外のページ: 「このページには注文がありません」と 1 ページ目へのリンク", () => {
    render(<OrderHistoryList history={history({ items: [], page: 5, total: 12, has_more: false })} />);
    expect(screen.getByTestId("history-out-of-range")).toHaveTextContent("このページには注文がありません");
    expect(screen.getByRole("link", { name: "1 ページ目へ" })).toHaveAttribute("href", "/mypage");
  });

  it("商品名に HTML・スクリプトを含んでも文字列として表示する（エスケープ。ST-SEC-54）", () => {
    const evil = `<script>alert(1)</script><img src=x onerror=alert(1)>`;
    const { container } = render(<OrderHistoryList history={history({ items: [item({ first_item_name: evil, item_count: 1 })] })} />);
    expect(screen.getByTestId("history-item")).toHaveTextContent(evil);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("UT-WEB-22 注文詳細", () => {
  const cases: [OrderStatus, number | null][] = [
    ["pending_payment", 0],
    ["accepted", 1],
    ["preparing", 2],
    ["shipped", 3],
    ["delivered", 4],
    ["pickup_expired", null],
    ["cancelled", null],
    ["payment_failed", null],
  ];

  it.each(cases)("状態 %s の完了段数は %s（取消・期限切れ・決済失敗は進捗バーなし）", (status, steps) => {
    expect(progressSteps(status)).toBe(steps);
    render(<OrderDetail order={makeOrder({ status, status_label: `表示名-${status}` })} />);
    if (steps === null) {
      expect(screen.queryByTestId("order-progress")).not.toBeInTheDocument();
    } else {
      const bar = screen.getByTestId("order-progress");
      expect(bar).toHaveAttribute("data-done", String(steps));
      expect(within(bar).getAllByRole("listitem").filter((li) => li.getAttribute("data-state") === "done")).toHaveLength(steps);
    }
    // 状態名のバッジは常に出る
    expect(screen.getByTestId("order-status-label")).toHaveTextContent(`表示名-${status}`);
  });

  it("進捗の段の名前: 配送「受付 → 出荷準備 → 出荷済 → 配達完了」、店舗「受付 → 準備中 → 受け取り可能 → 受渡済」", () => {
    expect([...DELIVERY_STEPS]).toEqual(["受付", "出荷準備", "出荷済", "配達完了"]);
    expect([...STORE_STEPS]).toEqual(["受付", "準備中", "受け取り可能", "受渡済"]);
    render(<OrderDetail order={makeOrder({ ...STORE_PATCH, status: "shipped", status_label: "店舗に到着（受け取り可能）" })} />);
    const bar = screen.getByTestId("order-progress");
    for (const label of STORE_STEPS) expect(bar).toHaveTextContent(label);
    expect(bar.querySelector('[aria-current="step"]')).toHaveTextContent("受け取り可能");
  });

  it("店舗受け取り: 店舗名・住所とコード（ABCD-2345）を出す。コードが null なら枠ごと出さない", () => {
    const { unmount } = render(<OrderDetail order={makeOrder({ ...STORE_PATCH, status: "preparing", status_label: "店舗へ準備中" })} />);
    expect(screen.getByTestId("store-info")).toHaveTextContent("デモ店 東京");
    expect(screen.getByTestId("pickup-code")).toHaveTextContent("ABCD-2345");
    expect(screen.queryByTestId("tracking")).not.toBeInTheDocument();
    unmount();

    render(<OrderDetail order={makeOrder({ ...STORE_PATCH, status: "delivered", pickup_code: null, status_label: "受け渡し済" })} />);
    expect(screen.getByTestId("store-info")).toBeInTheDocument();
    expect(screen.queryByTestId("pickup-code-block")).not.toBeInTheDocument();
  });

  it("配送: お届け先・追跡番号（API が返したときだけ）を出す", () => {
    const { unmount } = render(<OrderDetail order={makeOrder({ status: "shipped", status_label: "出荷済（配送中）", tracking_number: "1234-5678-9012", shipping_fee: 550, total: 5080 })} />);
    expect(screen.getByTestId("tracking")).toHaveTextContent("1234-5678-9012");
    expect(screen.getByTestId("shipping-summary")).toHaveTextContent("〒000-0001");
    expect(screen.queryByTestId("pickup-code-block")).not.toBeInTheDocument();
    unmount();

    render(<OrderDetail order={makeOrder({ tracking_number: null })} />);
    expect(screen.queryByTestId("tracking")).not.toBeInTheDocument();
  });

  it("明細・金額（小計・送料・合計・うち消費税）とマイページへ戻るリンク", () => {
    render(<OrderDetail order={makeOrder({ shipping_fee: 550, total: 5080, tax_included: 461 })} />);
    expect(screen.getAllByTestId("order-item")).toHaveLength(2);
    const amounts = screen.getByTestId("amount-summary");
    expect(amounts).toHaveTextContent("小計");
    expect(amounts).toHaveTextContent("¥4,530");
    expect(amounts).toHaveTextContent("¥550");
    expect(amounts).toHaveTextContent("¥5,080");
    expect(amounts).toHaveTextContent("うち消費税");
    expect(screen.getByRole("link", { name: "マイページへ戻る" })).toHaveAttribute("href", "/mypage");
    expect(screen.getByText(/2026\/10\/24 10:15/)).toBeInTheDocument();
  });

  it("氏名・商品名にスクリプトを含んでも実行されない（エスケープ）", () => {
    const evil = `"><img src=x onerror=alert(1)>`;
    const { container } = render(<OrderDetail order={makeOrder({ ship_name: evil, items: [{ product_name: evil, color: "x", size: "M", unit_price: 1, quantity: 1, line_total: 1 }] })} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain(evil);
  });
});
