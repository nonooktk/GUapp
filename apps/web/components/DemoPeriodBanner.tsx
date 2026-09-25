/**
 * 期間限定公開の帯（公開追補 設計仕様書 6 章・DS-DEC-50）。
 * ヘッダーの上・全ページ共通。終了日は `untilDisplay`（`YYYY/MM/DD` 済み文字列）として
 * サーバー側（layout.tsx）から渡す。null なら何も描画しない。
 *
 * 色だけで意味を伝えない: 文言そのものに「期間限定」「デモ」であることを明示する
 * （基準の色トークンのみで警告色を新設せず、既存の `--color-fg` / `--color-line` を使う）。
 */
export default function DemoPeriodBanner({ untilDisplay }: { untilDisplay: string | null }) {
  if (!untilDisplay) return null;

  return (
    <div
      role="status"
      className="w-full border-b border-line bg-line px-4 py-2 text-center text-sm text-fg"
    >
      講義レビュー用のデモとして、{untilDisplay} まで期間限定で公開しています
    </div>
  );
}
