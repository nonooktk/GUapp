"""リポジトリ層。SQL はここだけに置く（SQLAlchemy Core／ORM。文字列連結禁止。プラン 5 章）。

公開商品の基底クエリは `repositories.products.published_products()` の 1 か所（B7）。
一覧・詳細・関連・カート追加の全経路がそれを通る。
"""
