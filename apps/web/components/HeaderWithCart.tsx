"use client";

import Header from "@/components/Header";
import { useCart } from "@/components/CartProvider";

/** ヘッダーを CartProvider の点数に接続する（UT-WEB-01）。Header 自体は props だけの表示部品のまま残す */
export default function HeaderWithCart() {
  const { itemCount } = useCart();
  return <Header cartCount={itemCount} />;
}
