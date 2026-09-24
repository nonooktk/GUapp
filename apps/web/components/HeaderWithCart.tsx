"use client";

import Header from "@/components/Header";
import { useCart } from "@/components/CartProvider";
import type { Category } from "@/lib/types";

export interface HeaderWithCartProps {
  /** layout（Server Component）が GET /categories で取得したカテゴリ階層。失敗時は null */
  categories?: Category[] | null;
}

/** ヘッダーを CartProvider の点数に接続する（UT-WEB-01）。Header 自体は props だけの表示部品のまま残す */
export default function HeaderWithCart({ categories = null }: HeaderWithCartProps) {
  const { itemCount } = useCart();
  return <Header cartCount={itemCount} categories={categories} />;
}
