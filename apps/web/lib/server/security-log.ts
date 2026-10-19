import "server-only";

import { resolveClientIp } from "@/lib/client-ip";
import { getEnv } from "@/lib/server/env";
import { maskIp, writeRejectionLog } from "@/lib/security-log";

/**
 * Route Handler 向けの拒否ログ（S9）。Request から path・method・IP を取り出して 1 行書く。
 * 本文・ヘッダ・Cookie は読まない。環境変数が読めない状況（単体テストなど）でも落とさず、信頼ホップ 0 で IP を決める。
 */
export function logRejection(request: Request, info: { event: string; status: number; code: string }): void {
  let hops = 0;
  try {
    hops = getEnv().TRUSTED_PROXY_HOPS;
  } catch {
    hops = 0;
  }
  let path = "";
  try {
    path = new URL(request.url).pathname;
  } catch {
    path = "";
  }
  writeRejectionLog({
    event: info.event,
    path,
    method: request.method,
    status: info.status,
    code: info.code,
    ip: maskIp(resolveClientIp(request.headers, { trustedProxyHops: hops })),
  });
}
