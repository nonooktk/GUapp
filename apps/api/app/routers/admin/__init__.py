"""管理 API のルーター（`/api/v1/admin/*`。設計仕様書 P2 追補c 4.0・DS-DEC-107・109）。

担当レーン: C-1（C-2・C-3 は変更せず、コーディネーターに依頼する）。

**既定拒否**: ログインとログアウトを除くすべての管理ルートを、
`dependencies=[Depends(require_staff)]` つきの 1 つのルーター（`_guarded`）にまとめる。
ルートを足した人が認証の依存関数を書き忘れても、
無認証では通らない（会員のセッションは 403、管理用セッションなしは 401）。新しいルートは
`_guarded.include_router(...)` の行に足す。`OPEN_ADMIN_ROUTES` に無いルートが `require_staff` を
持たないことは、IT-ADM-01〜03 が `app.routes` を実行時に列挙して確かめる。

内部トークン（`X-Internal-Token`）は `main.build_protected_router` が `/api/v1` 全体に掛ける。

| ファイル     | 内容                                                     | 担当 |
| ------------ | -------------------------------------------------------- | ---- |
| `auth.py`    | ログイン・ログアウト〈開放〉・`GET /me`                  | C-1  |
| `products.py`| 商品一覧・詳細・更新・在庫の更新                          | C-2  |
| `settings.py`| 設定の取得・更新                                         | C-2  |
| `orders.py`  | 注文の検索・詳細・状態の更新                              | C-3  |
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.admin_session import require_staff
from app.routers.admin import auth, orders, products, settings

# 管理用セッションを要しないルート（メソッドと完全なパス）。この 2 本だけ（DS-API-050・050a）
OPEN_ADMIN_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/v1/admin/auth/login"),
        ("POST", "/api/v1/admin/auth/logout"),
    }
)

# ログインとログアウト（管理用セッションを要しない）
_open = APIRouter(tags=["admin-auth"])
_open.include_router(auth.public_router)

# それ以外はすべてここ。ルーター単位で `require_staff` を掛ける（既定拒否）
_guarded = APIRouter(dependencies=[Depends(require_staff)])
_guarded.include_router(auth.guarded_router, tags=["admin-auth"])
_guarded.include_router(products.router)
_guarded.include_router(settings.router)
_guarded.include_router(orders.router)

router = APIRouter(prefix="/admin")
router.include_router(_open)
router.include_router(_guarded)
