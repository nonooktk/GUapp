/**
 * 日時表示（純粋関数）。FastAPI の `ordered_at` は UTC の ISO 8601。画面は JST（Asia/Tokyo）で `2026/09/18 12:04` の形にする。
 * タイムゾーン指定の無い文字列（`2026-09-18T03:04:05`）は UTC と見なして `Z` を補う。
 */

const HAS_OFFSET = /(Z|[+-]\d{2}:?\d{2})$/i;

export function formatJst(iso: string): string {
  if (typeof iso !== "string" || iso.length === 0) return "";
  const normalized = HAS_OFFSET.test(iso) ? iso : `${iso}Z`;
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return "";
  const parts = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? "";
  // ja-JP の hour は 0 時が "24" になる実装があるため 2 桁に揃え直す
  const hour = String(Number(get("hour")) % 24).padStart(2, "0");
  return `${get("year")}/${get("month")}/${get("day")} ${hour}:${get("minute")}`;
}
