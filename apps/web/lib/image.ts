/**
 * 商品画像 URL の組み立て（純粋関数）。
 * FastAPI の `image_path` は `products/001/1.jpg` の形。表示 URL は `IMAGE_BASE_URL + "/" + image_path`。
 * image_path が null（画像未登録）なら null を返し、呼び出し側は灰色の枡だけ描く。
 * `IMAGE_BASE_URL` はサーバー側 env なので、Server Component が解決した base をクライアントへ props で渡す
 * （公開 URL であり秘密ではない）。
 */
export function imageUrl(baseUrl: string, imagePath: string | null | undefined): string | null {
  if (!imagePath) return null;
  const base = baseUrl.replace(/\/+$/, "");
  const path = imagePath.replace(/^\/+/, "");
  return `${base}/${path}`;
}
