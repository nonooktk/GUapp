/**
 * 性別区分の表示名と URL パラメータ（設計仕様書 6.3・6.4）。
 * URL は `/products?gender=women|men|kids_teen`（FastAPI の gender 値と同じ）。
 */

export const GENDERS = [
  { slug: "women", label: "WOMEN" },
  { slug: "men", label: "MEN" },
  { slug: "kids_teen", label: "KIDS・TEEN" },
] as const;

export type GenderSlug = (typeof GENDERS)[number]["slug"];

export function isGenderSlug(value: string | undefined): value is GenderSlug {
  return GENDERS.some((g) => g.slug === value);
}

export function genderLabel(slug: string | undefined): string | null {
  return GENDERS.find((g) => g.slug === slug)?.label ?? null;
}
