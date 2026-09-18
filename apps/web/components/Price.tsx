import { formatYen } from "@/lib/format";

/**
 * 税込価格の表示（デザイン基準 v1 3 章「価格表示」）。`¥1,990`（半角 ¥・カンマ区切り、UT-WEB-04 の formatYen）の後ろに
 * 小さく「（税込）」（--text-xs・--color-fg-muted）を付けられる。サイズ・ウェイト・色は呼び出し側の className で決める
 * （商品カード: text-lg font-bold／詳細: text-2xl font-bold）。セール・会員価格の --color-accent 出し分けは P1 では価格が変動しないため未実装。
 */
export default function Price({
  amount,
  taxNote = false,
  className = "",
}: {
  amount: number;
  taxNote?: boolean;
  className?: string;
}) {
  return (
    <span className={className}>
      <span className="tabular-nums">{formatYen(amount)}</span>
      {taxNote && <span className="ml-1 text-xs font-normal tracking-normal text-fg-muted">（税込）</span>}
    </span>
  );
}
