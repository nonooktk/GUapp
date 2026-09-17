import "server-only";

import { randomBytes } from "node:crypto";

/** 匿名カートトークンを生成する。暗号学的乱数 32 バイトを base64url 化（43 文字） */
export function generateCartToken(): string {
  return randomBytes(32).toString("base64url");
}
