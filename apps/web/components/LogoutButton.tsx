"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import Button from "@/components/Button";
import { useToast } from "@/components/Toast";
import { authErrorMessage } from "@/lib/auth-messages";
import { errorParts, logout } from "@/lib/client/auth-api";

/**
 * ログアウト（マイページ。設計仕様書 6.4・DS-API-033）。確認ダイアログなしで `POST /api/auth/logout` を呼び、
 * 成功したら `/` へ `router.replace` して `router.refresh()`（ヘッダーの会員アイコンを「ログイン」に戻す）。
 * 失敗しても BFF は `sid` を消して返すので、トーストで知らせたうえで同じく描き直す。
 */

export default function LogoutButton() {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const inflight = useRef(false);

  const onClick = async () => {
    if (inflight.current) return;
    inflight.current = true;
    setBusy(true);
    try {
      await logout();
      router.replace("/");
      router.refresh();
    } catch (err) {
      const { status, body } = errorParts(err);
      toast.show({ kind: "error", message: authErrorMessage(status, body) });
      inflight.current = false;
      setBusy(false);
      router.refresh();
    }
  };

  return (
    <Button variant="secondary" size="md" busy={busy} busyLabel="処理中…" onClick={onClick} data-testid="logout">
      ログアウト
    </Button>
  );
}
