"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import Button, { buttonClass } from "@/components/Button";
import { AUTH_MESSAGES, authErrorMessage } from "@/lib/auth-messages";
import { errorParts, verifyEmail } from "@/lib/client/auth-api";

/**
 * メール確認 DS-SCR-007（設計仕様書 6.3・DS-API-031・DS-DEC-74、テスト UT-WEB-19・AT-20）。
 * ボタンを押すまで POST しない（ページを開いただけでは確認しない。メールのリンクを自動で開くセキュリティ製品にトークンを消費させない）。
 * 押すと 1 回だけ送る。成功は「確認が完了しました」と /mypage へのリンク、404 は「リンクが無効か、期限が切れています」。
 */

export default function VerifyEmailButton({ token }: { token: string }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "invalid" | "error">("idle");
  const [message, setMessage] = useState<string>("");
  const inflight = useRef(false);

  const onClick = async () => {
    if (inflight.current) return;
    inflight.current = true;
    setState("busy");
    try {
      await verifyEmail(token);
      setState("done");
    } catch (err) {
      const { status, body } = errorParts(err);
      if (status === 404) {
        setState("invalid");
      } else {
        setMessage(authErrorMessage(status, body));
        setState("error");
        inflight.current = false;
      }
    }
  };

  return (
    <div className="mx-auto max-w-md space-y-6">
      <h1 className="text-xl font-light tracking-heading">メールアドレスの確認</h1>
      {state === "done" ? (
        <>
          <p role="status" className="rounded-sm border border-success bg-success/10 p-4 text-sm font-bold" data-testid="verify-done">
            確認が完了しました
          </p>
          <Link href="/mypage" className={buttonClass({ variant: "primary", size: "lg", full: true })}>
            マイページへ
          </Link>
        </>
      ) : state === "invalid" ? (
        <p role="alert" className="text-sm font-bold text-danger" data-testid="verify-invalid">
          ⚠ {AUTH_MESSAGES.invalidLink}
        </p>
      ) : (
        <>
          <p className="text-sm text-fg-muted">下のボタンを押すと、メールアドレスの確認が完了します。</p>
          {state === "error" && (
            <p role="alert" className="text-sm font-bold text-danger" data-testid="verify-error">
              ⚠ {message}
            </p>
          )}
          <Button
            variant="primary"
            size="lg"
            full
            busy={state === "busy"}
            busyLabel="確認中…"
            onClick={onClick}
            data-testid="verify-submit"
          >
            メールアドレスを確認する
          </Button>
        </>
      )}
    </div>
  );
}
