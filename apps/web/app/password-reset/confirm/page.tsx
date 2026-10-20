import type { Metadata } from "next";
import { InvalidLinkNotice, PasswordResetConfirmForm } from "@/components/PasswordResetForms";
import { isEmailToken } from "@/lib/auth-validation";
import { firstParam } from "@/lib/safe-next";

/**
 * パスワード再設定の確定 DS-SCR-007（設計仕様書 6.3）。`?token=` が無い・形（43 文字の base64url）が違うときは
 * /password-reset へのリンクつきの案内を出す。メールのリンクのトークンを外部へ漏らさないよう Referrer は送らない。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "新しいパスワードの設定 | GU EC サイト",
  referrer: "no-referrer",
  robots: { index: false },
};

export default async function PasswordResetConfirmPage({ searchParams }: PageProps<"/password-reset/confirm">) {
  const sp = await searchParams;
  const token = firstParam(sp.token);
  if (!isEmailToken(token)) return <InvalidLinkNotice />;
  return <PasswordResetConfirmForm token={token} />;
}
