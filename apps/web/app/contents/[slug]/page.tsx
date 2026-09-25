import { notFound } from "next/navigation";
import Breadcrumb from "@/components/Breadcrumb";
import LoadError from "@/components/LoadError";
import { UpstreamUnavailableError } from "@/lib/server/api";
import { getContent } from "@/lib/server/contents";

/**
 * FAQ・静的ページ DS-SCR-012（設計仕様書 P2 追補a 6.4、テスト ST-F028-01〜03・AT-11）。
 * `/contents/{slug}` で 5 種の slug（faq／terms／privacy／tokushoho／company）を共通レイアウトで表示する。
 * 本文はプレーンテキストとして React の既定エスケープのみで描画する（`dangerouslySetInnerHTML` を使わない。DS-DEC-38）。
 * 特商法（`tokushoho`）だけは「項目名→内容」の定義リストで表示する（6.4）。
 * FastAPI の 404（存在しない・kind 対象外・掲載期間外のいずれも区別しない）は notFound()、接続不可は「読み込めませんでした」。
 */

export const dynamic = "force-dynamic";

const headingClass = "text-xl font-light tracking-heading";

/** `項目名：内容` の行を定義リストの1組みに分ける。コロンが無い行（末尾の注記など）はそのまま段落で返す */
function splitDefinitionLine(line: string): { term: string; desc: string } | null {
  const idx = line.indexOf("：");
  if (idx <= 0) return null;
  return { term: line.slice(0, idx), desc: line.slice(idx + 1) };
}

function TokushohoBody({ body }: { body: string }) {
  const lines = body.split("\n").filter((l) => l.length > 0);
  return (
    <dl className="divide-y divide-line border-t border-line text-sm">
      {lines.map((line, i) => {
        const pair = splitDefinitionLine(line);
        if (!pair) {
          return (
            <p key={i} className="py-3 text-fg-muted">
              {line}
            </p>
          );
        }
        return (
          <div key={i} className="grid gap-1 py-3 sm:grid-cols-[10rem_1fr] sm:gap-4">
            <dt className="font-bold text-fg">{pair.term}</dt>
            <dd className="whitespace-pre-line text-fg">{pair.desc}</dd>
          </div>
        );
      })}
    </dl>
  );
}

export default async function ContentDetailPage({ params }: PageProps<"/contents/[slug]">) {
  const { slug } = await params;

  let result;
  try {
    result = await getContent(slug);
  } catch (err) {
    if (err instanceof UpstreamUnavailableError) {
      return <LoadError what="ページ" />;
    }
    throw err;
  }
  if (!result.ok) {
    if (result.status === 404) notFound();
    console.error("[contents/[slug]] failed", { status: result.status, code: result.error.code });
    return <LoadError what="ページ" />;
  }

  const content = result.data;

  return (
    <article className="space-y-6">
      <Breadcrumb items={[{ label: "ホーム", href: "/" }, { label: content.title }]} />
      <h1 className={headingClass}>{content.title}</h1>
      {content.slug === "tokushoho" ? (
        <TokushohoBody body={content.body} />
      ) : (
        <p className="whitespace-pre-line text-sm leading-relaxed">{content.body}</p>
      )}
    </article>
  );
}
