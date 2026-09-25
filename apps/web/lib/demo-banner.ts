/**
 * 期間限定公開の帯に出す終了日の解釈（公開追補 設計仕様書 6 章・DS-DEC-50）。
 *
 * `DEMO_PUBLIC_UNTIL` は実行時の環境変数（`YYYY-MM-DD`）。`NEXT_PUBLIC_` を付けると
 * ビルド時に埋め込まれてコード変更なしの延長ができなくなるため使わない。
 * 未設定なら帯を出さない。形式が不正なら帯を出さずログに警告する（例外は投げない）。
 * 表示形式は `YYYY/MM/DD`。
 */

const DATE_FORMAT = /^(\d{4})-(\d{2})-(\d{2})$/;

function isValidCalendarDate(year: number, month: number, day: number): boolean {
  if (month < 1 || month > 12) return false;
  const date = new Date(Date.UTC(year, month - 1, day));
  // UTC で組み立てた日付を分解し直し、繰り上がり（例: 2/30 → 3/2）が起きていないか確認する
  return (
    date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
  );
}

/**
 * `DEMO_PUBLIC_UNTIL` の値を検証し、表示用の `YYYY/MM/DD` 文字列に変換する。
 * 未設定・空文字は警告せず null。形式不正・実在しない日付は警告して null。
 */
export function parseDemoPublicUntil(
  raw: string | undefined,
  warn: (message: string) => void = console.warn,
): string | null {
  const trimmed = (raw ?? "").trim();
  if (trimmed === "") return null;

  const match = DATE_FORMAT.exec(trimmed);
  if (!match) {
    warn(`[demo-banner] DEMO_PUBLIC_UNTIL の形式が不正です（YYYY-MM-DD 形式で指定してください）: ${JSON.stringify(raw)}`);
    return null;
  }

  const [, yearStr, monthStr, dayStr] = match;
  const year = Number(yearStr);
  const month = Number(monthStr);
  const day = Number(dayStr);

  if (!isValidCalendarDate(year, month, day)) {
    warn(`[demo-banner] DEMO_PUBLIC_UNTIL に実在しない日付が指定されました: ${JSON.stringify(raw)}`);
    return null;
  }

  return `${yearStr}/${monthStr}/${dayStr}`;
}
