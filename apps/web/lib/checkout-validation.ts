/**
 * 注文手続きフォーム（DS-SCR-005）の入力検査と正規化（純粋関数。設計仕様書 4.4 DS-PRC-014-1 の入力形式表と同じ規則）。
 * - サーバー（Pydantic）と同じ規則をクライアントでも検査して赤字表示する（ST-F013-02）
 * - 郵便番号・電話はハイフン・空白を除いた ASCII 数字だけで桁を数える（全角数字は入力時に半角へ寄せる）
 * - `ship_address` は 都道府県・市区町村・番地・建物 を全角スペースで結合し、結合後 200 文字以内
 * - サーバーの 400 `validation_error {fields:[{name, reason}]}` も同じ項目名に対応付ける
 */

export const PREFECTURES = [
  "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
  "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
  "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県", "愛知県",
  "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
  "鳥取県", "島根県", "岡山県", "広島県", "山口県",
  "徳島県", "香川県", "愛媛県", "高知県",
  "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
] as const;

export interface CheckoutFormValues {
  name: string;
  postal: string;
  prefecture: string;
  city: string;
  street: string;
  building: string;
  phone: string;
  email: string;
}

export type CheckoutField = keyof CheckoutFormValues;
export type CheckoutErrors = Partial<Record<CheckoutField, string>>;

export const EMPTY_CHECKOUT_FORM: CheckoutFormValues = {
  name: "",
  postal: "",
  prefecture: "",
  city: "",
  street: "",
  building: "",
  phone: "",
  email: "",
};

/** 全角スペース（住所の結合に使う） */
export const ADDRESS_SEPARATOR = "　";
export const MAX_NAME_LENGTH = 50;
export const MAX_ADDRESS_LENGTH = 200;
export const MAX_EMAIL_LENGTH = 254;

/** 文字数はコードポイントで数える（サロゲートペアの絵文字などを 1 文字と見る） */
export function charLength(s: string): number {
  return Array.from(s).length;
}

/** 全角数字・全角ハイフン類を半角に寄せ、数字とハイフン以外を落とす（郵便番号・電話の入力時に使う） */
export function normalizeDigitsInput(raw: string): string {
  return raw
    .replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
    .replace(/[ー−‐－―]/g, "-")
    .replace(/[^0-9-]/g, "");
}

/** ハイフン・空白を除いた数字だけの文字列（送信値。サーバーの `^[0-9]{7}$` 等に合わせる） */
export function digitsOnly(raw: string): string {
  return normalizeDigitsInput(raw).replace(/-/g, "");
}

/** 都道府県・市区町村・番地・建物 を全角スペースで結合する（空の建物は落とす） */
export function joinShipAddress(v: Pick<CheckoutFormValues, "prefecture" | "city" | "street" | "building">): string {
  return [v.prefecture, v.city, v.street, v.building]
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
    .join(ADDRESS_SEPARATOR);
}

/** 実用上の形式検査。Pydantic の EmailStr（email-validator）はドット付きドメインを要求するので同じ厳しさにする */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(s: string): boolean {
  return s.length <= MAX_EMAIL_LENGTH && EMAIL_RE.test(s);
}

export const MESSAGES = {
  required: "入力してください",
  select: "選択してください",
  name_too_long: `${MAX_NAME_LENGTH} 文字以内で入力してください`,
  postal: "郵便番号は 7 桁の数字で入力してください",
  phone: "電話番号は 10〜11 桁の数字で入力してください",
  email: "メールアドレスの形式が正しくありません",
  address_too_long: `住所は合わせて ${MAX_ADDRESS_LENGTH} 文字以内で入力してください`,
} as const;

/** クライアント側の必須・形式検査。エラーの無い項目はキーごと持たない */
export function validateCheckoutForm(v: CheckoutFormValues): CheckoutErrors {
  const errors: CheckoutErrors = {};

  const name = v.name.trim();
  if (name.length === 0) errors.name = MESSAGES.required;
  else if (charLength(name) > MAX_NAME_LENGTH) errors.name = MESSAGES.name_too_long;

  const postal = digitsOnly(v.postal);
  if (v.postal.trim().length === 0) errors.postal = MESSAGES.required;
  else if (!/^[0-9]{7}$/.test(postal)) errors.postal = MESSAGES.postal;

  if (!v.prefecture) errors.prefecture = MESSAGES.select;
  else if (!(PREFECTURES as readonly string[]).includes(v.prefecture)) errors.prefecture = MESSAGES.select;

  if (v.city.trim().length === 0) errors.city = MESSAGES.required;
  if (v.street.trim().length === 0) errors.street = MESSAGES.required;

  if (!errors.prefecture && !errors.city && !errors.street) {
    if (charLength(joinShipAddress(v)) > MAX_ADDRESS_LENGTH) errors.street = MESSAGES.address_too_long;
  }

  const phone = digitsOnly(v.phone);
  if (v.phone.trim().length === 0) errors.phone = MESSAGES.required;
  else if (!/^[0-9]{10,11}$/.test(phone)) errors.phone = MESSAGES.phone;

  const email = v.email.trim();
  if (email.length === 0) errors.email = MESSAGES.required;
  else if (!isValidEmail(email)) errors.email = MESSAGES.email;

  return errors;
}

/** フォーム値から `POST /orders` の配送先項目（冪等キー・金額以外）を作る。検査を通った値に対して呼ぶ */
export function toShippingBody(v: CheckoutFormValues): {
  ship_name: string;
  ship_postal_code: string;
  ship_address: string;
  ship_phone: string;
  guest_email: string;
} {
  return {
    ship_name: v.name.trim(),
    ship_postal_code: digitsOnly(v.postal),
    ship_address: joinShipAddress(v),
    ship_phone: digitsOnly(v.phone),
    guest_email: v.email.trim(),
  };
}

/** サーバーの項目名 → フォームの項目。`ship_address` は結合先なので番地の欄に出す */
const SERVER_FIELD_MAP: Record<string, CheckoutField> = {
  ship_name: "name",
  ship_postal_code: "postal",
  ship_address: "street",
  ship_phone: "phone",
  guest_email: "email",
};

const REASON_MESSAGE: Record<string, string> = {
  required: MESSAGES.required,
  format: "形式が正しくありません",
  too_long: "文字数が多すぎます",
  out_of_range: "範囲外の値です",
};

/**
 * 400 `validation_error` の `fields` をフォームのエラー表示に対応付ける（ST-F013-02）。
 * 未知の項目名は捨てる（内部名を画面に出さない）。対応付けられた項目が 1 つも無ければ空。
 */
export function mapServerFieldErrors(fields: unknown): CheckoutErrors {
  const errors: CheckoutErrors = {};
  if (!Array.isArray(fields)) return errors;
  for (const f of fields) {
    if (typeof f !== "object" || f === null) continue;
    const { name, reason } = f as { name?: unknown; reason?: unknown };
    if (typeof name !== "string") continue;
    const field = SERVER_FIELD_MAP[name];
    if (!field) continue;
    const specific =
      field === "postal" && reason === "format"
        ? MESSAGES.postal
        : field === "phone" && reason === "format"
          ? MESSAGES.phone
          : field === "email" && reason === "format"
            ? MESSAGES.email
            : REASON_MESSAGE[typeof reason === "string" ? reason : ""] ?? "入力内容を確認してください";
    errors[field] = specific;
  }
  return errors;
}
