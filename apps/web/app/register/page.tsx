import type { Metadata } from "next";
import RegisterForm from "@/components/RegisterForm";

/** 会員登録 DS-SCR-007（設計仕様書 6.3）。フォーム本体は RegisterForm（クライアント） */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "会員登録 | GU EC サイト" };

export default function RegisterPage() {
  return <RegisterForm />;
}
