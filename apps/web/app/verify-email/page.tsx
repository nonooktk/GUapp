import type { Metadata } from "next";
import { InvalidLinkNotice } from "@/components/PasswordResetForms";
import VerifyEmailButton from "@/components/VerifyEmailButton";
import { isEmailToken } from "@/lib/auth-validation";
import { firstParam } from "@/lib/safe-next";

/**
 * メール確認 DS-SCR-007（設計仕様書 6.3・DS-DEC-74）。ページを開いただけでは確認しない（ボタンで POST する）。
 * `?token=` が無い・形が違うときは案内だけ出す。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "メールアドレスの確認 | GU EC サイト",
  referrer: "no-referrer",
  robots: { index: false },
};

export default async function VerifyEmailPage({ searchParams }: PageProps<"/verify-email">) {
  const sp = await searchParams;
  const token = firstParam(sp.token);
  if (!isEmailToken(token)) {
    return <InvalidLinkNotice title="メールアドレスの確認" href="/mypage" linkLabel="マイページへ" />;
  }
  return <VerifyEmailButton token={token} />;
}
