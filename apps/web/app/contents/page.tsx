import Breadcrumb from "@/components/Breadcrumb";
import LoadError from "@/components/LoadError";
import { formatJstDate } from "@/lib/datetime";
import { loadOrNull } from "@/lib/server/catalog";
import { getContents } from "@/lib/server/contents";

/**
 * コンテンツ・お知らせ一覧 DS-SCR-011（設計仕様書 P2 追補a 6.3、テスト ST-F030-01/02・AT-12）。
 * クエリ `?kind=news` でお知らせのみ、無指定は特集＋お知らせを両方表示する。
 * 日付表示は JST（`YYYY-MM-DD`）に変換する（DS-DEC-40。判定自体は API 側で UTC のまま）。
 */

export const dynamic = "force-dynamic";

const headingClass = "text-xl font-light tracking-heading";
const CONTENT_LIMIT_MAX = 20;

export default async function ContentsPage({ searchParams }: PageProps<"/contents">) {
  const sp = await searchParams;
  const kindParam = Array.isArray(sp.kind) ? sp.kind[0] : sp.kind;
  const newsOnly = kindParam === "news";

  const [news, feature] = await Promise.all([
    loadOrNull(getContents("news", CONTENT_LIMIT_MAX), "contents news"),
    newsOnly
      ? Promise.resolve(null)
      : loadOrNull(getContents("feature", CONTENT_LIMIT_MAX), "contents feature"),
  ]);

  return (
    <div className="space-y-10">
      <Breadcrumb items={[{ label: "ホーム", href: "/" }, { label: "お知らせ・特集" }]} />
      <h1 className={headingClass}>お知らせ・特集</h1>

      {!newsOnly && (
        <section aria-labelledby="feature-heading">
          <h2 id="feature-heading" className={`mb-4 ${headingClass}`}>
            特集
          </h2>
          {feature === null ? (
            <LoadError what="特集" />
          ) : feature.items.length === 0 ? (
            <p className="text-sm text-fg-muted">特集はまだありません</p>
          ) : (
            <ul className="space-y-4">
              {feature.items.map((item) => (
                <li key={item.slug} className="overflow-hidden rounded-sm border border-line">
                  <div className="flex h-24 items-center justify-center bg-linear-to-br from-fg to-fg-muted text-bg sm:h-32">
                    <span aria-hidden="true" className="text-xs tracking-heading">
                      特集バナー
                    </span>
                  </div>
                  <p className="px-4 py-3 text-sm font-bold">{item.title}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section aria-labelledby="news-heading">
        <h2 id="news-heading" className={`mb-4 ${headingClass}`}>
          お知らせ
        </h2>
        {news === null ? (
          <LoadError what="お知らせ" />
        ) : news.items.length === 0 ? (
          <p className="text-sm text-fg-muted">お知らせはまだありません</p>
        ) : (
          <ul className="divide-y divide-line rounded-sm border border-line text-sm">
            {news.items.map((item) => (
              <li key={item.slug} className="flex flex-wrap gap-x-4 gap-y-1 px-4 py-3">
                <span className="text-fg-muted">{formatJstDate(item.publish_from)}</span>
                <span>{item.title}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
