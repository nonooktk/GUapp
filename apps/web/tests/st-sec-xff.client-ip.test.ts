import { describe, expect, it } from "vitest";
import { isIpLike, resolveClientIp, stripPort } from "@/lib/client-ip";

// ST 実施記録 2026-09-24 の 🟡 対応: 利用者送信の X-Forwarded-For を信用しない（設計仕様書 8.2・7.6）。
// 優先順は X-Client-IP（App Service）→ TRUSTED_PROXY_HOPS で右から切った XFF → 接続元 127.0.0.1
const h = (headers: Record<string, string>) => new Headers(headers);

describe("resolveClientIp: 利用者が付けた X-Forwarded-For は使わない（hops=0）", () => {
  it("X-Forwarded-For: 203.0.113.9 を付けても 127.0.0.1", () => {
    expect(resolveClientIp(h({ "x-forwarded-for": "203.0.113.9" }), { trustedProxyHops: 0 })).toBe("127.0.0.1");
  });

  it("複数値でも同じ（先頭を採らない）", () => {
    expect(resolveClientIp(h({ "x-forwarded-for": "203.0.113.9, 10.0.0.1" }), { trustedProxyHops: 0 })).toBe("127.0.0.1");
  });

  it("ヘッダが無ければ 127.0.0.1", () => {
    expect(resolveClientIp(h({}), { trustedProxyHops: 0 })).toBe("127.0.0.1");
  });

  it("接続元 IP が分かればそれをフォールバックに使う", () => {
    expect(resolveClientIp(h({ "x-forwarded-for": "203.0.113.9" }), { trustedProxyHops: 0, connectionIp: "10.1.2.3" })).toBe("10.1.2.3");
  });
});

describe("resolveClientIp: X-Client-IP（App Service front end）は hops>=1 のときだけ最優先", () => {
  it("hops>=1 で X-Client-IP があればそれ。利用者の X-Forwarded-For より優先", () => {
    const headers = h({ "x-client-ip": "198.51.100.7", "x-forwarded-for": "203.0.113.9, 198.51.100.7" });
    expect(resolveClientIp(headers, { trustedProxyHops: 1 })).toBe("198.51.100.7");
    expect(resolveClientIp(headers, { trustedProxyHops: 2 })).toBe("198.51.100.7");
  });

  it("hops=0（プロキシ無し）では利用者が付けた X-Client-IP も無視して接続元", () => {
    expect(resolveClientIp(h({ "x-client-ip": "198.51.100.7" }), { trustedProxyHops: 0 })).toBe("127.0.0.1");
    expect(resolveClientIp(h({ "x-client-ip": "198.51.100.7" }), { trustedProxyHops: 0, connectionIp: "10.1.2.3" })).toBe("10.1.2.3");
  });

  it("X-Client-IP が IPv6 でも通る", () => {
    expect(resolveClientIp(h({ "x-client-ip": "2001:db8::1" }), { trustedProxyHops: 1 })).toBe("2001:db8::1");
  });

  it("X-Client-IP が不正（unknown・空）なら無視して次へ進む", () => {
    expect(resolveClientIp(h({ "x-client-ip": "unknown" }), { trustedProxyHops: 1 })).toBe("127.0.0.1");
    expect(resolveClientIp(h({ "x-client-ip": "" }), { trustedProxyHops: 1 })).toBe("127.0.0.1");
    expect(resolveClientIp(h({ "x-client-ip": "unknown", "x-forwarded-for": "a, 198.51.100.7" }), { trustedProxyHops: 1 })).toBe("198.51.100.7");
  });
});

describe("resolveClientIp: TRUSTED_PROXY_HOPS で X-Forwarded-For を右から数える", () => {
  const xff = h({ "x-forwarded-for": "203.0.113.1, 203.0.113.2, 203.0.113.3" });

  it("hops=1 → 末尾（信頼プロキシが追記した位置）", () => {
    expect(resolveClientIp(xff, { trustedProxyHops: 1 })).toBe("203.0.113.3");
  });

  it("hops=2 → 右から 2 番目", () => {
    expect(resolveClientIp(xff, { trustedProxyHops: 2 })).toBe("203.0.113.2");
  });

  it("hops=3 → 右から 3 番目（= 先頭）", () => {
    expect(resolveClientIp(xff, { trustedProxyHops: 3 })).toBe("203.0.113.1");
  });

  it("要素数より hops が大きければ信頼できる位置が無いので 127.0.0.1", () => {
    expect(resolveClientIp(xff, { trustedProxyHops: 4 })).toBe("127.0.0.1");
    expect(resolveClientIp(h({ "x-forwarded-for": "203.0.113.9" }), { trustedProxyHops: 2 })).toBe("127.0.0.1");
  });

  it("利用者が先頭に偽 IP を置いても、右から数えるので影響しない", () => {
    expect(resolveClientIp(h({ "x-forwarded-for": "1.1.1.1, 198.51.100.7" }), { trustedProxyHops: 1 })).toBe("198.51.100.7");
  });

  it("App Service 形式の IP:port はポートを落とす", () => {
    expect(resolveClientIp(h({ "x-forwarded-for": "1.1.1.1, 198.51.100.7:51234" }), { trustedProxyHops: 1 })).toBe("198.51.100.7");
    expect(resolveClientIp(h({ "x-forwarded-for": "[2001:db8::1]:443" }), { trustedProxyHops: 1 })).toBe("2001:db8::1");
  });

  it("信頼位置の値が不正（空・unknown・非 IP・巨大値）なら 127.0.0.1 にフォールバック", () => {
    expect(resolveClientIp(h({ "x-forwarded-for": "203.0.113.9, " }), { trustedProxyHops: 1 })).toBe("127.0.0.1");
    expect(resolveClientIp(h({ "x-forwarded-for": "203.0.113.9, unknown" }), { trustedProxyHops: 1 })).toBe("127.0.0.1");
    expect(resolveClientIp(h({ "x-forwarded-for": "evil.example.com" }), { trustedProxyHops: 1 })).toBe("127.0.0.1");
    expect(resolveClientIp(h({ "x-forwarded-for": "999.1.1.1" }), { trustedProxyHops: 1 })).toBe("127.0.0.1");
    expect(resolveClientIp(h({ "x-forwarded-for": "a".repeat(100) }), { trustedProxyHops: 1 })).toBe("127.0.0.1");
  });

  it("hops が整数でない・負数なら 0 とみなす", () => {
    expect(resolveClientIp(xff, { trustedProxyHops: Number.NaN })).toBe("127.0.0.1");
    expect(resolveClientIp(xff, { trustedProxyHops: -1 })).toBe("127.0.0.1");
    expect(resolveClientIp(xff, { trustedProxyHops: 1.5 })).toBe("127.0.0.1");
  });
});

describe("isIpLike / stripPort", () => {
  it.each(["127.0.0.1", "203.0.113.9", "::1", "2001:db8::1", "::ffff:10.0.0.1"])("%s は IP らしい", (v) => {
    expect(isIpLike(v)).toBe(true);
  });

  it.each(["", "unknown", "abc", "256.0.0.1", "1.2.3", "evil.example.com", "203.0.113.9\r\nX-Injected: 1"])("%j は IP ではない", (v) => {
    expect(isIpLike(v)).toBe(false);
  });

  it("stripPort は IPv4:port と [IPv6]:port だけ剥がす", () => {
    expect(stripPort("198.51.100.7:51234")).toBe("198.51.100.7");
    expect(stripPort("[2001:db8::1]:443")).toBe("2001:db8::1");
    expect(stripPort("[2001:db8::1]")).toBe("2001:db8::1");
    expect(stripPort("2001:db8::1")).toBe("2001:db8::1");
    expect(stripPort("198.51.100.7")).toBe("198.51.100.7");
  });
});
