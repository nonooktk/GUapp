"use client";

import Button from "@/components/Button";
import { useChat } from "@/components/chat/ChatProvider";

/**
 * 商品詳細の「この商品について質問する」（設計仕様書 P2 追補d 6.5・DS-SCR-003・REQ-FR-904、テスト UT-WEB-AI-09）。
 * 押すとチャットを開き、この商品の `product_id` を文脈として保持する（パネル上部に「{商品名} について質問中」）。
 */
export default function AskAssistantButton({ productId, productName }: { productId: number; productName: string }) {
  const { openChat } = useChat();
  return (
    <Button variant="secondary" size="md" onClick={() => openChat({ product: { id: productId, name: productName } })}>
      この商品について質問する
    </Button>
  );
}
