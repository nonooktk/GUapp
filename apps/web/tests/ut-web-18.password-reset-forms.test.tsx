import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InvalidLinkNotice, PasswordResetConfirmForm, PasswordResetRequestForm } from "@/components/PasswordResetForms";
import { clearCookies, jsonResponse, mockFetch, setCsrfCookie } from "./helpers/client";

// テスト設計書 UT-WEB-18（パスワード再設定フォーム）。設計仕様書 6.3・DS-API-034・035・DS-DEC-71・75・AT-19
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace, refresh: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

beforeEach(() => setCsrfCookie());
afterEach(() => {
  vi.unstubAllGlobals();
  replace.mockReset();
  clearCookies();
});

const TOKEN = "tokenCCCC_-0123456789abcdefghijklmnopqrstu"; // gitleaks:allow // pragma: allowlist secret（43 文字）
const NEW_PW = "brand-new-password-1"; // pragma: allowlist secret

describe("UT-WEB-18 要求フォーム", () => {
  it("送信後は登録の有無を区別せず常に同じ案内（200）。本文は email だけ", async () => {
    const { calls } = mockFetch(() => jsonResponse(200, { status: "accepted" }));
    render(<PasswordResetRequestForm />);
    expect(screen.getByRole("note", { name: "デモに関する注意" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^メールアドレス/), { target: { value: "anyone@example.com" } });
    fireEvent.click(screen.getByTestId("reset-request-submit"));
    expect(await screen.findByTestId("reset-request-done")).toHaveTextContent("入力されたメールアドレスが登録されていれば、再設定のメールを送りました");
    expect(calls[0].url).toBe("/api/auth/password-reset/request");
    expect(calls[0].body).toEqual({ email: "anyone@example.com" });
  });

  it("空・形式不正は送信しない", () => {
    const { fn } = mockFetch(() => jsonResponse(200, { status: "accepted" }));
    render(<PasswordResetRequestForm />);
    fireEvent.click(screen.getByTestId("reset-request-submit"));
    expect(fn).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/^メールアドレス/), { target: { value: "bad" } });
    fireEvent.click(screen.getByTestId("reset-request-submit"));
    expect(fn).not.toHaveBeenCalled();
    expect(screen.getByText("メールアドレスの形式を確認してください")).toBeInTheDocument();
  });

  it("429 は alert。422 unsupported_value はメール欄", async () => {
    mockFetch(() => jsonResponse(429, { code: "rate_limited" }));
    const { unmount } = render(<PasswordResetRequestForm />);
    fireEvent.change(screen.getByLabelText(/^メールアドレス/), { target: { value: "a@example.com" } });
    fireEvent.click(screen.getByTestId("reset-request-submit"));
    expect(await screen.findByTestId("reset-request-error")).toHaveTextContent("試行が多すぎます");
    unmount();

    vi.unstubAllGlobals();
    mockFetch(() => jsonResponse(422, { code: "unsupported_value", field: "email" }));
    render(<PasswordResetRequestForm />);
    fireEvent.change(screen.getByLabelText(/^メールアドレス/), { target: { value: "a@example.org" } });
    fireEvent.click(screen.getByTestId("reset-request-submit"));
    expect(await screen.findByText("このサイトでは使えないメールアドレスです")).toBeInTheDocument();
  });
});

describe("UT-WEB-18 確定フォーム", () => {
  const fill = (pw: string, confirm: string) => {
    fireEvent.change(screen.getByLabelText(/^新しいパスワード（8/), { target: { value: pw } });
    fireEvent.change(screen.getByLabelText(/^新しいパスワード（確認）/), { target: { value: confirm } });
  };

  it("確認入力が一致しないときは送信しない", () => {
    const { fn } = mockFetch(() => jsonResponse(200, { status: "ok" }));
    render(<PasswordResetConfirmForm token={TOKEN} />);
    fill(NEW_PW, "different-password");
    fireEvent.click(screen.getByTestId("reset-confirm-submit"));
    expect(fn).not.toHaveBeenCalled();
    expect(screen.getByText("確認用のパスワードが一致しません")).toBeInTheDocument();
  });

  it("成功: token・password を送り、/login?reset=1 へ移る（自動ログインしない）", async () => {
    const { calls } = mockFetch(() => jsonResponse(200, { status: "ok" }));
    render(<PasswordResetConfirmForm token={TOKEN} />);
    fill(NEW_PW, NEW_PW);
    fireEvent.click(screen.getByTestId("reset-confirm-submit"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login?reset=1"));
    expect(calls[0].url).toBe("/api/auth/password-reset/confirm");
    expect(calls[0].body).toEqual({ token: TOKEN, password: NEW_PW });
  });

  it("404: 「リンクが無効か、期限が切れています」と再要求へのリンク", async () => {
    mockFetch(() => jsonResponse(404, { code: "not_found" }));
    render(<PasswordResetConfirmForm token={TOKEN} />);
    fill(NEW_PW, NEW_PW);
    fireEvent.click(screen.getByTestId("reset-confirm-submit"));
    expect(await screen.findByTestId("invalid-link")).toHaveTextContent("リンクが無効か、期限が切れています");
    expect(screen.getByRole("link", { name: /もう一度送る/ })).toHaveAttribute("href", "/password-reset");
    expect(replace).not.toHaveBeenCalled();
  });

  it("422 weak_password はパスワード欄（トークンは消費されないのでフォームが残る）", async () => {
    mockFetch(() => jsonResponse(422, { code: "weak_password", field: "password" }));
    render(<PasswordResetConfirmForm token={TOKEN} />);
    fill("password1234", "password1234"); // pragma: allowlist secret
    fireEvent.click(screen.getByTestId("reset-confirm-submit"));
    expect(await screen.findByText("よくあるパスワードやメールアドレスと同じ値は使えません")).toBeInTheDocument();
    expect(screen.getByTestId("reset-confirm-submit")).toBeInTheDocument();
  });

  it("InvalidLinkNotice（token が無い・形が違うとき）は再要求へのリンクつき", () => {
    render(<InvalidLinkNotice />);
    expect(screen.getByRole("alert")).toHaveTextContent("リンクが無効か、期限が切れています");
    expect(screen.getByRole("link")).toHaveAttribute("href", "/password-reset");
  });
});
