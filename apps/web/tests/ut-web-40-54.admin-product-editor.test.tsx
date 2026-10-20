import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AdminProductEditor from "@/components/admin/AdminProductEditor";
import { ToastProvider } from "@/components/Toast";
import { clearCookies, jsonResponse, mockFetch, setCsrfCookie } from "./helpers/client";
import { makeAdminProduct } from "./helpers/admin";

// テスト設計書 UT-WEB-45（公開切替と価格。DS-SCR-015-2）。設計仕様書 P2 追補c 6.4・DS-DEC-113
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace, refresh: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

beforeEach(() => {
  setCsrfCookie();
});
afterEach(() => {
  vi.unstubAllGlobals();
  replace.mockReset();
  clearCookies();
});

function renderEditor(patch = {}) {
  return render(
    <ToastProvider>
      <AdminProductEditor product={makeAdminProduct(patch)} />
    </ToastProvider>,
  );
}
const price = () => screen.getByTestId("admin-price-input") as HTMLInputElement;
const priceSave = () => screen.getByTestId("admin-price-save");
const toggle = () => screen.getByTestId("admin-publish-toggle");
const state = () => screen.getByTestId("admin-published-state");

describe("UT-WEB-45 公開切替と価格", () => {
  it("商品名・公開状態・価格・在庫の行が出る。名前は編集できない（入力欄がない）", () => {
    renderEditor();
    expect(screen.getByTestId("admin-product-name")).toHaveTextContent("スムースコットンT（レディース）");
    expect(state()).toHaveTextContent("公開");
    expect(price().value).toBe("1990");
    expect(screen.getAllByTestId("admin-stock-row")).toHaveLength(2);
    expect(screen.getAllByRole("textbox")).toHaveLength(1 + 2); // 価格 + 在庫 2 行
  });

  it("公開の切り替えは確認ダイアログを経る: キャンセルでは送らない", () => {
    const { fn } = mockFetch(() => jsonResponse(200, {}));
    renderEditor();
    fireEvent.click(toggle());
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("公開を止めると、お客様は商品を見られなくなります");
    fireEvent.click(within(dialog).getByRole("button", { name: "キャンセル" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(fn).not.toHaveBeenCalled();
    expect(state()).toHaveTextContent("公開");
  });

  it("OK で published と expected_published だけを PATCH し、表示を非公開にする。戻すときも確認を経る", async () => {
    const { calls } = mockFetch((_u, init) => {
      const b = JSON.parse(init.body as string) as { published: boolean };
      return jsonResponse(200, { product_id: 12, published: b.published, price_incl_tax: 1990, changed: true, updated_at: "x" });
    });
    renderEditor();
    fireEvent.click(toggle());
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "非公開にする" }));
    await waitFor(() => expect(state()).toHaveTextContent("非公開"));
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/admin/api/products/12");
    expect(calls[0].method).toBe("PATCH");
    expect(calls[0].body).toEqual({ published: false, expected_published: true });
    expect(screen.getByTestId("toast")).toHaveTextContent("非公開にしました");
    expect(toggle()).toHaveTextContent("公開する");

    fireEvent.click(toggle());
    expect(screen.getByRole("dialog")).toHaveTextContent("公開すると、お客様が商品を見られるようになります");
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "公開する" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].body).toEqual({ published: true, expected_published: false });
  });

  it("価格の保存: 変更した項目 price_incl_tax と expected_price_incl_tax(画面の値)だけを送る。確認ダイアログなし", async () => {
    const { calls } = mockFetch(() => jsonResponse(200, { product_id: 12, published: true, price_incl_tax: 2490, changed: true, updated_at: "x" }));
    renderEditor();
    expect(priceSave()).toBeDisabled();
    fireEvent.change(price(), { target: { value: "2490" } });
    expect(priceSave()).toBeEnabled();
    fireEvent.click(priceSave());
    await waitFor(() => expect(screen.getByTestId("toast")).toHaveTextContent("保存しました"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls[0].body).toEqual({ price_incl_tax: 2490, expected_price_incl_tax: 1990 });
    expect(Object.keys(calls[0].body as object).sort()).toEqual(["expected_price_incl_tax", "price_incl_tax"]);
    expect(priceSave()).toBeDisabled();
  });

  it("価格と公開の両方を変えた場合: 公開の確認で送るのは公開の項目だけ、価格の保存で送るのは価格の項目だけ（互いの項目を混ぜない）", async () => {
    const { calls } = mockFetch((_u, init) => {
      const b = JSON.parse(init.body as string) as Record<string, unknown>;
      return jsonResponse(200, {
        product_id: 12,
        published: typeof b.published === "boolean" ? b.published : true,
        price_incl_tax: typeof b.price_incl_tax === "number" ? b.price_incl_tax : 1990,
        changed: true,
        updated_at: "x",
      });
    });
    renderEditor();
    fireEvent.change(price(), { target: { value: "2000" } });
    fireEvent.click(toggle());
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "非公開にする" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toEqual({ published: false, expected_published: true });
    expect(price().value).toBe("2000"); // 入力中の価格は消えない
    await waitFor(() => expect(toggle()).toBeEnabled());
    fireEvent.click(priceSave());
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].body).toEqual({ price_incl_tax: 2000, expected_price_incl_tax: 1990 });
  });

  it("409 stale_data（価格）: current で表示を更新し、項目の近くに文言。続けて保存すると expected は current", async () => {
    const { calls } = mockFetch((_u, init) => {
      const b = JSON.parse(init.body as string) as { expected_price_incl_tax: number };
      return b.expected_price_incl_tax === 1990
        ? jsonResponse(409, { code: "stale_data", field: "price_incl_tax", current: 2100 })
        : jsonResponse(200, { product_id: 12, published: true, price_incl_tax: 2200, changed: true, updated_at: "x" });
    });
    renderEditor();
    fireEvent.change(price(), { target: { value: "2200" } });
    fireEvent.click(priceSave());
    await waitFor(() => expect(screen.getByTestId("admin-price-error")).toBeInTheDocument());
    expect(screen.getByTestId("admin-price-error")).toHaveTextContent("他の操作で値が変わっていました（現在の値：2,100）");
    expect(price().value).toBe("2100");
    fireEvent.change(price(), { target: { value: "2200" } });
    fireEvent.click(priceSave());
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].body).toEqual({ price_incl_tax: 2200, expected_price_incl_tax: 2100 });
  });

  it("409 stale_data（公開状態）: current(false)で表示を非公開に直し、案内を出す", async () => {
    mockFetch(() => jsonResponse(409, { code: "stale_data", field: "published", current: false }));
    renderEditor();
    fireEvent.click(toggle());
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "非公開にする" }));
    await waitFor(() => expect(screen.getByTestId("admin-publish-error")).toBeInTheDocument());
    expect(screen.getByTestId("admin-publish-error")).toHaveTextContent("現在の値：非公開");
    expect(state()).toHaveTextContent("非公開");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("422（API 側の範囲外）は価格欄の下に範囲を示す", async () => {
    mockFetch(() => jsonResponse(422, { code: "unsupported_value", field: "price_incl_tax" }));
    renderEditor();
    fireEvent.change(price(), { target: { value: "500" } });
    fireEvent.click(priceSave());
    await waitFor(() => expect(screen.getByTestId("admin-price-error")).toHaveTextContent("価格は 1 以上 1,000,000 以下で入力してください"));
  });

  it.each([
    ["", "価格を入力してください"],
    ["0", "価格は 1 以上 1,000,000 以下で入力してください"],
    ["-5", "価格は 1 以上 1,000,000 以下で入力してください"],
    ["1000001", "価格は 1 以上 1,000,000 以下で入力してください"],
    ["12.5", "価格の形式が正しくありません"],
    ["abc", "価格の形式が正しくありません"],
  ])("価格の入力 %j は送信せず入力欄の下に表示する", (value, message) => {
    const { fn } = mockFetch(() => jsonResponse(200, {}));
    renderEditor();
    fireEvent.change(price(), { target: { value } });
    fireEvent.click(priceSave());
    expect(fn).not.toHaveBeenCalled();
    expect(screen.getByTestId("admin-price-error")).toHaveTextContent(message);
  });

  it("401 は /admin/login?expired=1 へ移す", async () => {
    mockFetch(() => jsonResponse(401, { code: "unauthorized" }));
    renderEditor();
    fireEvent.change(price(), { target: { value: "2000" } });
    fireEvent.click(priceSave());
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin/login?expired=1"));
    expect(screen.queryByTestId("admin-price-error")).toBeNull();
  });
});
