import { formatYen } from "@/lib/format";

/** 税込価格の表示。`¥1,990` の後ろに小さく「（税込）」を付けられる（UT-WEB-04 の formatYen を使う） */
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
      {taxNote && <span className="ml-1 text-xs font-normal text-gray-600">（税込）</span>}
    </span>
  );
}
