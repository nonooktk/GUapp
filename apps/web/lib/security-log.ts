/**
 * 拒否ログ（セキュリティ強化 S9）の純粋関数。`server-only` を付けず、proxy.ts と Route Handler の両方から呼ぶ。
 *
 * 出すのは event／path／method／status／code／ip の 6 項目だけ。本文・Cookie・トークン・クエリ・個人情報は出さない。
 * ip は末尾を丸める（IPv4 は末尾 1 オクテットを 0、IPv6 は先頭 3 ブロック以外を 0）。
 * 1 回の拒否につき `console.warn` を 1 回、JSON 文字列 1 行で書く（Azure のログストリームで 1 行 1 件になる）。
 */

export interface RejectionLogEntry {
  /** 拒否した理由の種類（例: csrf_token_rejected・origin_rejected・payload_too_large・rate_limited・validation_rejected） */
  event: string;
  path: string;
  method: string;
  status: number;
  /** 利用者に返した `code`（forbidden・payload_too_large・rate_limited・validation_error） */
  code: string;
  /** 丸め済みの IP（`maskIp` の結果） */
  ip: string;
}

const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.\d{1,3}$/;

/** IPv4 は末尾 1 オクテットを 0 に、IPv6 は先頭 3 ブロック以外を 0 に丸める。IP と読めなければ "unknown" */
export function maskIp(ip: string): string {
  const value = ip.trim();
  const v4 = IPV4.exec(value);
  if (v4) return `${v4[1]}.${v4[2]}.${v4[3]}.0`;
  if (!value.includes(":")) return "unknown";

  // IPv4 射影（::ffff:203.0.113.45）は IPv4 として丸める
  const mapped = /^(?:::ffff:|0:0:0:0:0:ffff:)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})$/i.exec(value);
  if (mapped) return maskIp(mapped[1]);

  const halves = value.split("::");
  if (halves.length > 2) return "unknown";
  const head = halves[0] === "" ? [] : halves[0].split(":");
  const tail = halves.length === 2 && halves[1] !== "" ? halves[1].split(":") : [];
  const fill = 8 - head.length - tail.length;
  if (halves.length === 1 ? head.length !== 8 : fill < 1) return "unknown";
  const blocks = [...head, ...Array<string>(halves.length === 2 ? fill : 0).fill("0"), ...tail];
  if (blocks.length !== 8 || !blocks.every((b) => /^[0-9a-fA-F]{1,4}$/.test(b))) return "unknown";
  return [...blocks.slice(0, 3).map((b) => b.toLowerCase()), "0", "0", "0", "0", "0"].join(":");
}

/** クエリは付けない。注文番号は個人に紐づくので伏せ、極端に長い値は切る */
export function sanitizePath(pathname: string): string {
  const withoutQuery = pathname.split("?")[0];
  return withoutQuery.replace(/GU-\d{6}-[0-9A-Za-z]{4,16}/g, ":order_number").slice(0, 200);
}

/** 拒否ログを 1 行（JSON）で `console.warn` に書く。`ip` は呼び出し側で `maskIp` に通した値 */
export function writeRejectionLog(entry: RejectionLogEntry): void {
  console.warn(
    JSON.stringify({
      event: entry.event,
      path: sanitizePath(entry.path),
      method: entry.method,
      status: entry.status,
      code: entry.code,
      ip: entry.ip,
    }),
  );
}
