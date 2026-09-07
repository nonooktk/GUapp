# docs 生成ツール（Markdown 正本 → docx）

| スクリプト | 役割 |
| --- | --- |
| render_mermaid.py | 設計仕様書 md の ```mermaid ブロックを mermaid-cli（npx @mermaid-js/mermaid-cli）で PNG 化 |
| build_sd_docx.py | 設計仕様書 md → docx（表・等幅ブロック・PNG 埋め込み。縦長図は高さ 225mm に自動縮小） |
| build_td_docx.py | テスト設計書 md → docx（build_sd_docx.py の派生） |
| fix_docx.py | 既存 docx の修復。異常な tblInd 削除・tblPr の要素順・空 PAGE フィールド・view=print |

注意
- パスはメイン PC（Desktop/GUapp・Desktop/DocsMaker）の絶対パスを前提にしている。他 PC では先頭の定数を書き換える
- Mermaid のメッセージ内に `;` を書くと mermaid-cli が構文エラーになる（全角スラッシュ等に置き換える）
- ページ高さ（約 246mm）を超えるインライン画像があると Word はレイアウト不能になり、下書き表示に固定される
- 2026-09-07 以前に python-docx で生成した docx は表紙表の tblInd に巨大値が入っており Word が開けない状態だった。fix_docx.py を通せば直る
