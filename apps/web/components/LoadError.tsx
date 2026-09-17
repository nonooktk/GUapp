/** データ取得に失敗したときの共通表示。FastAPI 停止時も build・描画を通すためにページ側で使う */
export default function LoadError({ what = "データ" }: { what?: string }) {
  return (
    <div role="alert" className="rounded-lg border border-gray-300 bg-gray-50 p-6 text-center text-sm text-gray-700">
      {what}を読み込めませんでした。時間をおいて再読み込みしてください。
    </div>
  );
}
