import type { Metadata } from "next";
import { PasswordResetRequestForm } from "@/components/PasswordResetForms";

/** パスワード再設定の要求 DS-SCR-007（設計仕様書 6.3）。登録の有無を区別しない案内は PasswordResetRequestForm */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "パスワードの再設定 | GU EC サイト" };

export default function PasswordResetPage() {
  return <PasswordResetRequestForm />;
}
