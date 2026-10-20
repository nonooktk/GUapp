import type { FitSummary as FitSummaryData } from "@/lib/types";

/**
 * サイズ感（購入者の声）DS-SCR-003（設計仕様書 6.6・DS-API-003 の `fit_summary`、テスト UT-WEB-24・AT-17）。
 * - `total` が 1 以上: 「全 N 件」と件数 3 つ（小さめ／ちょうどよい／大きめ）、件数に比例した幅の積み上げ棒。
 *   色だけに頼らないよう、棒の下に文字と件数の凡例を出す。割合は API から来ない（件数の比を棒の幅にするだけ。丸めで合計が 100 にならない問題を避ける）
 * - 0 件: 「サイズ感のレビューはまだありません」
 * Server Component から描ける（フックなし）。
 */

export const EMPTY_FIT_SUMMARY: FitSummaryData = { total: 0, small: 0, just: 0, large: 0 };

const SEGMENTS = [
  { key: "small", label: "小さめ", bar: "bg-fg-muted" },
  { key: "just", label: "ちょうどよい", bar: "bg-fg" },
  { key: "large", label: "大きめ", bar: "border border-fg bg-line" },
] as const;

export default function FitSummary({ summary }: { summary: FitSummaryData | null | undefined }) {
  const s = summary ?? EMPTY_FIT_SUMMARY;
  return (
    <section aria-labelledby="fit-heading" className="space-y-3 text-sm" data-testid="fit-summary">
      <h2 id="fit-heading" className="text-xl font-light tracking-heading">
        サイズ感（購入者の声）
      </h2>
      {s.total <= 0 ? (
        <p className="text-fg-muted" data-testid="fit-empty">
          サイズ感のレビューはまだありません
        </p>
      ) : (
        <>
          <p className="font-bold" data-testid="fit-total">
            全 {s.total} 件
          </p>
          {/* 件数に比例した幅（flex-grow = 件数）。0 件の区間は幅 0。棒そのものは装飾（意味は下の凡例が伝える） */}
          <div className="flex h-3 w-full overflow-hidden rounded-pill" aria-hidden="true" data-testid="fit-bar">
            {SEGMENTS.map((seg) => (
              <span
                key={seg.key}
                data-segment={seg.key}
                data-count={s[seg.key]}
                className={seg.bar}
                style={{ flexGrow: s[seg.key], flexBasis: 0 }}
              />
            ))}
          </div>
          <ul className="grid grid-cols-3 gap-2 text-center" aria-label="サイズ感の内訳">
            {SEGMENTS.map((seg) => (
              <li key={seg.key} data-testid={`fit-${seg.key}`}>
                <span aria-hidden="true" className={`mx-auto mb-1 block h-2 w-6 rounded-pill ${seg.bar}`} />
                <span className="block text-fg-muted">{seg.label}</span>
                <span className="block text-lg font-bold tabular-nums">{s[seg.key]}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
