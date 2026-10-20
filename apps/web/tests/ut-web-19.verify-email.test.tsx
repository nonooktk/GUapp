import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VerifyEmailButton from "@/components/VerifyEmailButton";
import { clearCookies, jsonResponse, mockFetch, setCsrfCookie } from "./helpers/client";

// テスト設計書 UT-WEB-19（メール確認ページ）。設計仕様書 6.3・DS-API-031・DS-DEC-74・AT-20
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

beforeEach(() => setCsrfCookie());
afterEach(() => {
  vi.unstubAllGlobals();
  clearCookies();
});

const TOKEN = "tokenDDDD_-0123456789abcdefghijklmnopqrstu"; // gitleaks:allow // pragma: allowlist secret（43 文字）

describe("UT-WEB-19 メール確認ページ", () => {
  it("描画しただけ（マウント時）では POST しない。ボタンを押すと 1 回だけ送る（連打しても 1 回）", async () => {
    const { fn, calls } = mockFetch(() => jsonResponse(200, { verified: true }));
    render(<VerifyEmailButton token={TOKEN} />);
    expect(fn).not.toHaveBeenCalled();
    const button = screen.getByTestId("verify-submit");
    fireEvent.click(button);
    fireEvent.click(button);
    await screen.findByTestId("verify-done");
    expect(fn).toHaveBeenCalledTimes(1);
    expect(calls[0].url).toBe("/api/auth/verify-email");
    expect(calls[0].body).toEqual({ token: TOKEN });
  });

  it("200: 「確認が完了しました」と /mypage へのリンク", async () => {
    mockFetch(() => jsonResponse(200, { verified: true }));
    render(<VerifyEmailButton token={TOKEN} />);
    fireEvent.click(screen.getByTestId("verify-submit"));
    expect(await screen.findByTestId("verify-done")).toHaveTextContent("確認が完了しました");
    expect(screen.getByRole("link", { name: "マイページへ" })).toHaveAttribute("href", "/mypage");
  });

  it("404: 「リンクが無効か、期限が切れています」", async () => {
    mockFetch(() => jsonResponse(404, { code: "not_found" }));
    render(<VerifyEmailButton token={TOKEN} />);
    fireEvent.click(screen.getByTestId("verify-submit"));
    expect(await screen.findByTestId("verify-invalid")).toHaveTextContent("リンクが無効か、期限が切れています");
  });

  it("それ以外の失敗は文言を出し、やり直せる", async () => {
    mockFetch(() => jsonResponse(503, { code: "upstream_unavailable" }));
    render(<VerifyEmailButton token={TOKEN} />);
    fireEvent.click(screen.getByTestId("verify-submit"));
    expect(await screen.findByTestId("verify-error")).toHaveTextContent("接続できません");
    await waitFor(() => expect(screen.getByTestId("verify-submit")).not.toBeDisabled());
  });
});
