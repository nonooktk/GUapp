import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CartProvider } from "@/components/CartProvider";
import PurchasePanel from "@/components/PurchasePanel";
import RestockForm from "@/components/RestockForm";
import { ToastProvider } from "@/components/Toast";
import { RESTOCK_MESSAGES, restockErrorMessage } from "@/lib/restock-messages";
import type { Variant } from "@/lib/types";
import { clearCookies, jsonResponse, mockFetch, setCsrfCookie } from "./helpers/client";

// テスト設計書 UT-WEB-23（再入荷のお知らせの申込。DS-SCR-003）。設計仕様書 6.6・DS-API-007・DS-DEC-80・AT-16
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

beforeEach(() => setCsrfCookie());
afterEach(() => {
  vi.unstubAllGlobals();
  clearCookies();
});

const fillEmail = (v: string) => fireEvent.change(screen.getByLabelText(/^メールアドレス/), { target: { value: v } });
const submit = () => fireEvent.click(screen.getByTestId("restock-submit"));

describe("UT-WEB-23 申込フォーム", () => {
  it("200: 欄が消えて「申し込みました。入荷したらメールでお知らせします」。本文は variant_id・email だけ", async () => {
    const { calls } = mockFetch(() => jsonResponse(200, { status: "registered" }));
    render(<RestockForm variantId={4521} />);
    fillEmail("demo@example.com");
    submit();
    expect(await screen.findByTestId("restock-done")).toHaveTextContent("申し込みました。入荷したらメールでお知らせします");
    expect(screen.queryByTestId("restock-submit")).not.toBeInTheDocument();
    expect(calls[0].url).toBe("/api/restock-notifications");
    expect(calls[0].body).toEqual({ variant_id: 4521, email: "demo@example.com" });
  });

  it.each([
    [409, { code: "in_stock" }, "在庫が入りました。ページを読み込み直して、カートに入れてください"],
    [404, { code: "not_found" }, "この商品は申し込めません"],
    [422, { code: "limit_exceeded", field: "email", limit: 10 }, "申し込みの上限（10 件）に達しています"],
    [422, { code: "unsupported_value", field: "email" }, "このサイトでは使えないメールアドレスです"],
    [400, { code: "validation_error", fields: [{ name: "email", reason: "format" }] }, "メールアドレスの形式を確認してください"],
    [429, { code: "rate_limited" }, "しばらくしてからお試しください"],
  ])("%i の文言（フォームは残り、やり直せる）", async (status, body, message) => {
    mockFetch(() => jsonResponse(status, body));
    render(<RestockForm variantId={1} />);
    fillEmail("demo@example.com");
    submit();
    expect(await screen.findByText(message, { exact: false })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("restock-submit")).not.toBeDisabled());
    expect(screen.queryByTestId("restock-done")).not.toBeInTheDocument();
  });

  it("送信中は無効で、連打しても 1 回だけ送る", async () => {
    let resolve!: (r: Response) => void;
    const { fn } = mockFetch(() => new Promise<Response>((r) => (resolve = r)));
    render(<RestockForm variantId={1} />);
    fillEmail("demo@example.com");
    submit();
    await waitFor(() => expect(screen.getByTestId("restock-submit")).toBeDisabled());
    fireEvent.submit(screen.getByTestId("restock-submit").closest("form")!);
    expect(fn).toHaveBeenCalledTimes(1);
    resolve(jsonResponse(200, { status: "registered" }));
    await screen.findByTestId("restock-done");
  });

  it("空・形式不正のメールは送信しない（クライアント検査）", () => {
    const { fn } = mockFetch(() => jsonResponse(200, { status: "registered" }));
    render(<RestockForm variantId={1} />);
    submit();
    fillEmail("not-an-email");
    submit();
    expect(fn).not.toHaveBeenCalled();
    expect(screen.getByText(RESTOCK_MESSAGES.invalidEmail)).toBeInTheDocument();
  });

  it("restockErrorMessage: 未知のコードは汎用文言（内部のコードを画面に出さない）", () => {
    const r = restockErrorMessage(500, { code: "some_internal_code" });
    expect(r.message).toBe(RESTOCK_MESSAGES.generic);
    expect(r.message).not.toContain("some_internal_code");
  });
});

describe("UT-WEB-23 PurchasePanel への出し分け", () => {
  const variants: Variant[] = [
    { variant_id: 11, color: "ブラック", size: "M", in_stock: false },
    { variant_id: 12, color: "ブラック", size: "L", in_stock: true },
  ];

  function renderPanel() {
    return render(
      <ToastProvider>
        <CartProvider hasCartCookie={false}>
          <PurchasePanel productId={29} price={1990} colors={["ブラック"]} sizes={["M", "L"]} variants={variants} />
        </CartProvider>
      </ToastProvider>,
    );
  }

  it("色とサイズの両方を選び、その組み合わせが在庫切れのときだけ表示する", () => {
    renderPanel();
    // 色は 1 色なので自動選択済み、サイズ未選択
    expect(screen.queryByTestId("restock-form")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^サイズ M/ }));
    expect(screen.getByTestId("stock-status")).toHaveTextContent("在庫切れ");
    expect(screen.getByTestId("restock-form")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^サイズ L/ }));
    expect(screen.getByTestId("stock-status")).toHaveTextContent("在庫あり");
    expect(screen.queryByTestId("restock-form")).not.toBeInTheDocument();
  });

  it("組み合わせを変えると申込済みの表示を持ち越さず、選んだ variant_id で申し込む", async () => {
    const two: Variant[] = [
      { variant_id: 21, color: "ブラック", size: "M", in_stock: false },
      { variant_id: 22, color: "ブラック", size: "L", in_stock: false },
    ];
    const { calls } = mockFetch(() => jsonResponse(200, { status: "registered" }));
    render(
      <ToastProvider>
        <CartProvider hasCartCookie={false}>
          <PurchasePanel productId={29} price={1990} colors={["ブラック"]} sizes={["M", "L"]} variants={two} />
        </CartProvider>
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /^サイズ M/ }));
    fillEmail("demo@example.com");
    submit();
    await screen.findByTestId("restock-done");
    expect(calls[0].body).toEqual({ variant_id: 21, email: "demo@example.com" });

    fireEvent.click(screen.getByRole("button", { name: /^サイズ L/ }));
    expect(screen.queryByTestId("restock-done")).not.toBeInTheDocument();
    fillEmail("demo@example.com");
    submit();
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].body).toEqual({ variant_id: 22, email: "demo@example.com" });
  });
});
