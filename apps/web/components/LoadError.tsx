/** データ取得に失敗したときの共通表示。FastAPI 停止時も build・描画を通すためにページ側で使う */
export default function LoadError({ what = "データ" }: { what?: string }) {
  return (
    <div role="alert" className="rounded-sm border border-line bg-line/40 p-6 text-center text-sm text-fg-muted">
      {what}を読み込めませんでした。時間をおいて再読み込みしてください。
    </div>
  );
}
