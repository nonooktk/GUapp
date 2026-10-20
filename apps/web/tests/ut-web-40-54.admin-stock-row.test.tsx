import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AdminStockRow from "@/components/admin/AdminStockRow";
import { ToastProvider } from "@/components/Toast";
import type { AdminVariant } from "@/lib/admin-types";
import { clearCookies, jsonResponse, mockFetch, setCsrfCookie } from "./helpers/client";

// テスト設計書 UT-WEB-44（在庫の行。DS-SCR-015-2）。設計仕様書 P2 追補c 6.4・DS-DEC-114・115・113
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

const VARIANT: AdminVariant = { variant_id: 7, sku: "GU-029-BK-M", color: "ブラック", size: "M", stock: 0, restock_waiting: 2 };

function renderRow(variant: AdminVariant = VARIANT) {
  return render(
    <ToastProvider>
      <table>
        <tbody>
          <AdminStockRow variant={variant} />
        </tbody>
      </table>
    </ToastProvider>,
  );
}
const input = () => screen.getByTestId("admin-stock-input") as HTMLInputElement;
const save = () => screen.getByTestId("admin-stock-save");
const type = (v: string) => fireEvent.change(input(), { target: { value: v } });

describe("UT-WEB-44 在庫の行", () => {
  it("0 から 1 以上にする前に「再入荷待ちの N 件にメールを送ります」を出す。待ち件数は件数だけでメールアドレスは出さない", () => {
    renderRow();
    expect(screen.queryByTestId("admin-restock-note")).toBeNull();
    type("5");
    expect(screen.getByTestId("admin-restock-note")).toHaveTextContent("再入荷待ちの 2 件にメールを送ります");
    expect(screen.getByTestId("admin-restock-waiting")).toHaveTextContent("2 件");
    expect(screen.getByRole("row").textContent).not.toMatch(/@/);
    type("0");
    expect(screen.queryByTestId("admin-restock-note")).toBeNull();
  });

  it("在庫がもともと 1 以上の行では再入荷の案内を出さない", () => {
    renderRow({ ...VARIANT, stock: 4, restock_waiting: 0 });
    type("9");
    expect(screen.queryByTestId("admin-restock-note")).toBeNull();
  });

  it("成功（0→5・待ち 2 件）: expected_stock に画面の値(0)を入れて PATCH。トーストに前後の値と待ち件数。再入荷待ちは 0 件になる", async () => {
    const { calls } = mockFetch(() =>
      jsonResponse(200, { variant_id: 7, sku: "GU-029-BK-M", stock: 5, previous_stock: 0, changed: true, restock_waiting: 2 }),
    );
    renderRow();
    type("5");
    fireEvent.click(save());
    await waitFor(() => expect(screen.getByTestId("toast")).toBeInTheDocument());
    expect(screen.getByTestId("toast")).toHaveTextContent("在庫を 0 から 5 に更新しました。再入荷通知の対象は 2 件です");
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/admin/api/variants/7/stock");
    expect(calls[0].method).toBe("PATCH");
    expect(calls[0].body).toEqual({ stock: 5, expected_stock: 0 });
    expect(calls[0].headers.get("X-CSRF-Token")).toBeTruthy();
    expect(screen.getByTestId("admin-restock-waiting")).toHaveTextContent("0 件");
    expect(input().value).toBe("5");
    expect(save()).toBeDisabled();
  });

  it("再入荷でない更新（4→9）のトーストには再入荷通知の文言を付けない。次の保存の expected_stock は直前の結果(9)", async () => {
    const { calls } = mockFetch((_url, init) => {
      const b = JSON.parse(init.body as string) as { stock: number; expected_stock: number };
      return jsonResponse(200, { variant_id: 7, sku: "S", stock: b.stock, previous_stock: b.expected_stock, changed: true, restock_waiting: 0 });
    });
    renderRow({ ...VARIANT, stock: 4, restock_waiting: 0 });
    type("9");
    fireEvent.click(save());
    await waitFor(() => expect(screen.getByTestId("toast")).toHaveTextContent("在庫を 4 から 9 に更新しました"));
    expect(screen.getByTestId("toast").textContent).not.toContain("再入荷通知");
    type("3");
    fireEvent.click(save());
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].body).toEqual({ stock: 3, expected_stock: 9 });
  });

  it("同値では保存ボタンが無効で、送信しない", () => {
    const { fn } = mockFetch(() => jsonResponse(200, {}));
    renderRow();
    expect(save()).toBeDisabled();
    fireEvent.click(save());
    type("0");
    expect(save()).toBeDisabled();
    type("1");
    expect(save()).toBeEnabled();
    expect(fn).not.toHaveBeenCalled();
  });

  it("409 stale_data: current で行を更新して案内する。続けて保存すると expected_stock は current", async () => {
    const { calls } = mockFetch((_u, init) => {
      const b = JSON.parse(init.body as string) as { expected_stock: number };
      if (b.expected_stock === 0) return jsonResponse(409, { code: "stale_data", field: "stock", current: 3 });
      return jsonResponse(200, { variant_id: 7, sku: "S", stock: 8, previous_stock: 3, changed: true, restock_waiting: 0 });
    });
    renderRow();
    type("5");
    fireEvent.click(save());
    await waitFor(() => expect(screen.getByTestId("admin-stock-error")).toBeInTheDocument());
    expect(screen.getByTestId("admin-stock-error")).toHaveTextContent("他の操作で値が変わっていました（現在の値：3）。内容を確認してもう一度保存してください");
    expect(input().value).toBe("3");
    expect(save()).toBeDisabled();
    type("8");
    fireEvent.click(save());
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].body).toEqual({ stock: 8, expected_stock: 3 });
  });

  it("422（API 側の範囲外）は入力欄の下に範囲を示す", async () => {
    mockFetch(() => jsonResponse(422, { code: "limit_exceeded", field: "stock", limit: 9999 }));
    renderRow();
    type("100");
    fireEvent.click(save());
    await waitFor(() => expect(screen.getByTestId("admin-stock-error")).toHaveTextContent("在庫は 0 以上 9,999 以下で入力してください"));
    expect(input()).toHaveAttribute("aria-invalid", "true");
  });

  it.each([
    ["", "在庫を入力してください"],
    ["-1", "在庫は 0 以上 9,999 以下で入力してください"],
    ["10000", "在庫は 0 以上 9,999 以下で入力してください"],
    ["99999999999", "在庫は 0 以上 9,999 以下で入力してください"],
    ["1.5", "在庫の形式が正しくありません"],
    ["abc", "在庫の形式が正しくありません"],
    ["1e3", "在庫の形式が正しくありません"],
  ])("入力 %j は送信せず入力欄の下に表示する", (value, message) => {
    const { fn } = mockFetch(() => jsonResponse(200, {}));
    renderRow({ ...VARIANT, stock: 4 });
    type(value);
    fireEvent.click(save());
    expect(fn).not.toHaveBeenCalled();
    expect(within(screen.getByRole("row")).getByRole("alert")).toHaveTextContent(message);
  });

  it("上限ちょうど 9999 と下限 0 は送信する", async () => {
    const { calls } = mockFetch((_u, init) => {
      const b = JSON.parse(init.body as string) as { stock: number; expected_stock: number };
      return jsonResponse(200, { variant_id: 7, sku: "S", stock: b.stock, previous_stock: b.expected_stock, changed: true, restock_waiting: 0 });
    });
    renderRow({ ...VARIANT, stock: 4 });
    type("9999");
    fireEvent.click(save());
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toEqual({ stock: 9999, expected_stock: 4 });
    await act(async () => {});
    type("0");
    fireEvent.click(save());
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].body).toEqual({ stock: 0, expected_stock: 9999 });
  });

  it("401（セッション切れ）は /admin/login?expired=1 へ移す", async () => {
    mockFetch(() => jsonResponse(401, { code: "unauthorized" }));
    renderRow();
    type("5");
    fireEvent.click(save());
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin/login?expired=1"));
  });

  it("送信中は保存ボタンが無効で、連打しても 2 回送らない", async () => {
    let resolve!: (r: Response) => void;
    const { fn } = mockFetch(() => new Promise<Response>((r) => (resolve = r)));
    renderRow();
    type("5");
    fireEvent.click(save());
    await waitFor(() => expect(save()).toBeDisabled());
    fireEvent.click(save());
    expect(fn).toHaveBeenCalledTimes(1);
    resolve(jsonResponse(200, { variant_id: 7, sku: "S", stock: 5, previous_stock: 0, changed: true, restock_waiting: 2 }));
    await waitFor(() => expect(screen.getByTestId("toast")).toBeInTheDocument());
  });
});
