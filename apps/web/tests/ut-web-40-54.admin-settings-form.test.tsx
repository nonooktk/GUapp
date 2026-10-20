import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AdminSettingsForm from "@/components/admin/AdminSettingsForm";
import { ToastProvider } from "@/components/Toast";
import { clearCookies, jsonResponse, mockFetch, setCsrfCookie } from "./helpers/client";
import { ADMIN_SETTING_ITEMS } from "./helpers/admin";

// テスト設計書 UT-WEB-48（設定フォーム。DS-SCR-016）。設計仕様書 P2 追補c 6.6・DS-DEC-113・119
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

function renderForm() {
  return render(
    <ToastProvider>
      <AdminSettingsForm items={ADMIN_SETTING_ITEMS} />
    </ToastProvider>,
  );
}
const tax = () => screen.getByLabelText(/^消費税率/) as HTMLInputElement;
const fee = () => screen.getByLabelText("送料", { exact: true }) as HTMLInputElement;
const threshold = () => screen.getByLabelText(/^送料無料の下限/) as HTMLInputElement;
const saveBtn = () => screen.getByTestId("admin-settings-save");
const set = (el: HTMLInputElement, v: string) => fireEvent.change(el, { target: { value: v } });

function okResponse(patch: Partial<Record<string, string | number>> = {}, changed: string[] = ["shipping_fee"]) {
  return jsonResponse(200, {
    items: ADMIN_SETTING_ITEMS.map((i) => (i.key in patch ? { ...i, value: patch[i.key] } : i)),
    changed,
  });
}

describe("UT-WEB-48 設定フォーム", () => {
  it("3 項目の入力欄と、範囲の案内。payment_timeout_minutes は入力欄がなく表示のみ（変更できません）", () => {
    renderForm();
    expect(tax().value).toBe("0.10");
    expect(fee().value).toBe("550");
    expect(threshold().value).toBe("4990");
    expect(screen.getByText("0.00〜0.30")).toBeInTheDocument();
    expect(screen.getByText("0〜5000 円")).toBeInTheDocument();
    const ro = screen.getByTestId("setting-readonly-payment_timeout_minutes");
    expect(ro).toHaveTextContent("決済待ちの期限");
    expect(ro).toHaveTextContent("30");
    expect(ro).toHaveTextContent("変更できません");
    expect(ro.querySelector("input")).toBeNull();
    expect(screen.getAllByRole("textbox")).toHaveLength(3);
    expect(screen.getByText(/変更は次のアクセスからすべてのお客様の金額に反映されます/)).toBeInTheDocument();
  });

  it("変更がなければ保存ボタンが無効。戻せば再び無効になる", () => {
    renderForm();
    expect(saveBtn()).toBeDisabled();
    set(fee(), "600");
    expect(saveBtn()).toBeEnabled();
    set(fee(), "550");
    expect(saveBtn()).toBeDisabled();
  });

  it("1 項目だけ変更: 変更した項目と expected_*(画面の値)だけを送る", async () => {
    const { calls } = mockFetch(() => okResponse({ shipping_fee: 600 }));
    renderForm();
    set(fee(), "600");
    fireEvent.click(saveBtn());
    await waitFor(() => expect(screen.getByTestId("toast")).toHaveTextContent("保存しました"));
    expect(calls[0].url).toBe("/admin/api/settings");
    expect(calls[0].method).toBe("PATCH");
    expect(calls[0].body).toEqual({ shipping_fee: 600, expected_shipping_fee: 550 });
    expect(fee().value).toBe("600");
    expect(saveBtn()).toBeDisabled();
  });

  it("消費税率は文字列(\"0.08\")のまま送る。複数項目の変更は 1 回の PATCH にまとめる", async () => {
    const { calls } = mockFetch(() => okResponse({ tax_rate: "0.08", free_shipping_threshold: 5500 }, ["tax_rate", "free_shipping_threshold"]));
    renderForm();
    set(tax(), "0.08");
    set(threshold(), "5500");
    fireEvent.click(saveBtn());
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toEqual({
      tax_rate: "0.08",
      expected_tax_rate: "0.10",
      free_shipping_threshold: 5500,
      expected_free_shipping_threshold: 4990,
    });
  });

  it("payment_timeout_minutes や未知のキーは送らない", async () => {
    const { calls } = mockFetch(() => okResponse({ shipping_fee: 0 }));
    renderForm();
    set(fee(), "0");
    fireEvent.click(saveBtn());
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(Object.keys(calls[0].body as object).sort()).toEqual(["expected_shipping_fee", "shipping_fee"]);
  });

  it("応答の changed が空なら「変更はありませんでした」", async () => {
    mockFetch(() => okResponse({}, []));
    renderForm();
    set(fee(), "600");
    fireEvent.click(saveBtn());
    await waitFor(() => expect(screen.getByTestId("toast")).toHaveTextContent("変更はありませんでした"));
  });

  it.each([
    [() => tax(), "0.31", "消費税率は 0.00 以上 0.30 以下で入力してください"],
    [() => tax(), "1.00", "消費税率は 0.00 以上 0.30 以下で入力してください"],
    [() => tax(), "0.1", "消費税率の形式が正しくありません"],
    [() => tax(), "abc", "消費税率の形式が正しくありません"],
    [() => tax(), "", "消費税率を入力してください"],
    [() => fee(), "5001", "送料は 0 以上 5,000 以下で入力してください"],
    [() => fee(), "-1", "送料は 0 以上 5,000 以下で入力してください"],
    [() => fee(), "12.5", "送料の形式が正しくありません"],
    [() => threshold(), "100001", "送料無料の下限は 0 以上 100,000 以下で入力してください"],
  ])("範囲外・形の違いは送信せず項目の下に範囲を示す (%#)", (el, value, message) => {
    const { fn } = mockFetch(() => jsonResponse(200, {}));
    renderForm();
    set(el(), value);
    fireEvent.click(saveBtn());
    expect(fn).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(message);
  });

  it("上限・下限ちょうど（0.30・0.00・5000・0・100000）は送る", async () => {
    const { calls } = mockFetch(() => okResponse({ tax_rate: "0.30", shipping_fee: 5000, free_shipping_threshold: 100000 }, ["tax_rate"]));
    renderForm();
    set(tax(), "0.30");
    set(fee(), "5000");
    set(threshold(), "100000");
    fireEvent.click(saveBtn());
    await waitFor(() => expect(calls).toHaveLength(1));
  });

  it("422（API 側の範囲外）は該当項目の下に範囲を示す", async () => {
    mockFetch(() => jsonResponse(422, { code: "limit_exceeded", field: "shipping_fee", limit: 5000 }));
    renderForm();
    set(fee(), "4000");
    fireEvent.click(saveBtn());
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("送料は 0 以上 5,000 以下で入力してください"));
    expect(fee()).toHaveAttribute("aria-invalid", "true");
  });

  it("409 stale_data: その項目を current で更新して再操作を促す。続けて保存すると expected は current", async () => {
    const { calls } = mockFetch((_u, init) => {
      const b = JSON.parse(init.body as string) as { expected_shipping_fee: number };
      return b.expected_shipping_fee === 550
        ? jsonResponse(409, { code: "stale_data", field: "shipping_fee", current: 700 })
        : okResponse({ shipping_fee: 650 });
    });
    renderForm();
    set(fee(), "600");
    fireEvent.click(saveBtn());
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("他の操作で値が変わっていました（現在の値：700）。内容を確認してもう一度保存してください"));
    expect(fee().value).toBe("700");
    set(fee(), "650");
    fireEvent.click(saveBtn());
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].body).toEqual({ shipping_fee: 650, expected_shipping_fee: 700 });
  });

  it("409 stale_data（消費税率の文字列)", async () => {
    mockFetch(() => jsonResponse(409, { code: "stale_data", field: "tax_rate", current: "0.08" }));
    renderForm();
    set(tax(), "0.12");
    fireEvent.click(saveBtn());
    await waitFor(() => expect(tax().value).toBe("0.08"));
    expect(screen.getByRole("alert")).toHaveTextContent("現在の値：0.08");
  });

  it("401 は /admin/login?expired=1 へ移す", async () => {
    mockFetch(() => jsonResponse(401, { code: "unauthorized" }));
    renderForm();
    set(fee(), "600");
    fireEvent.click(saveBtn());
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin/login?expired=1"));
  });

  it("項目に結びつかない失敗(503)はフォーム上部の role=alert", async () => {
    mockFetch(() => jsonResponse(503, { code: "upstream_unavailable" }));
    renderForm();
    set(fee(), "600");
    fireEvent.click(saveBtn());
    await waitFor(() => expect(screen.getByTestId("admin-settings-error")).toHaveTextContent("サーバーに接続できません"));
  });
});
