"""管理操作の監査ログ（DS-PRC-054。設計仕様書 P2 追補c 4.6・5.4・DS-DEC-120）。

担当レーン: C-1（部品）。使うのは C-2（`admin.product.update`・`admin.stock.set`・
`admin.settings.update`）と C-3（`admin.order.status`・`admin.order.view`）、C-1 自身
（`admin.login`・`admin.logout`）。

- 更新と**同じトランザクション**で INSERT する（呼び出し側が COMMIT する）。INSERT が失敗したら
  例外がそのまま伝わり、呼び出し側が更新ごと ROLLBACK する（記録のない更新を残さない）
- `detail` に個人情報・秘密を入れない。禁止キーを再帰的に探し、1 つでもあれば `RuntimeError`
  （プログラムの誤り。500）にする
- アプリのコードに `audit_logs` の UPDATE・DELETE を書かない（UT-ADM-18 が静的に検査する）
- 値が変わらなかった更新（`changed: false`）は記録しない（呼び出し側が呼ばない）
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActorType, AuditLog

# 監査ログの action 名（5.4）。文字列を各所に散らさないための定数
ACTION_LOGIN = "admin.login"
ACTION_LOGOUT = "admin.logout"
ACTION_PRODUCT_UPDATE = "admin.product.update"
ACTION_STOCK_SET = "admin.stock.set"
ACTION_SETTINGS_UPDATE = "admin.settings.update"
ACTION_ORDER_STATUS = "admin.order.status"
ACTION_ORDER_VIEW = "admin.order.view"

# `detail` に入れてはいけないキー（9 種。小文字で比べる）と、接頭辞 `ship_`
FORBIDDEN_DETAIL_KEYS: frozenset[str] = frozenset(
    {
        "email",
        "name",
        "phone",
        "address",
        "postal_code",
        "pickup_code",
        "password",
        "token",
        "guest_email",
    }
)
FORBIDDEN_DETAIL_KEY_PREFIX = "ship_"


class HasStaffId(Protocol):
    """監査ログの `actor_id` に使う管理者。`CurrentStaff` がこれを満たす。"""

    @property
    def id(self) -> int: ...


def find_forbidden_key(detail: Any) -> str | None:
    """`detail`（入れ子の dict・list を含む）から禁止キーを 1 つ探す。無ければ None。"""
    if isinstance(detail, Mapping):
        for key, value in detail.items():
            lowered = str(key).lower()
            if lowered in FORBIDDEN_DETAIL_KEYS or lowered.startswith(FORBIDDEN_DETAIL_KEY_PREFIX):
                return str(key)
            found = find_forbidden_key(value)
            if found is not None:
                return found
    elif isinstance(detail, (list, tuple)):
        for value in detail:
            found = find_forbidden_key(value)
            if found is not None:
                return found
    return None


async def write_admin_audit(
    session: AsyncSession,
    staff: HasStaffId,
    *,
    action: str,
    target_type: str,
    target_id: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """管理操作を `audit_logs` に 1 行 INSERT して `flush` する（COMMIT は呼び出し側）。

    設計書: 4.6 DS-PRC-054、5.4（action ごとの target_type・target_id・detail）。

    - `staff`: `CurrentStaff`（`actor_type=staff`、`actor_id=staff.id`）
    - `action`: 上の `ACTION_*` 定数（5.4 の 7 種）
    - `target_type`・`target_id`: 5.4 の表のとおり（例: `"order"`・注文番号、`"variant"`・
      `variant_id` の文字列）。`target_id` は 64 文字以内の文字列
    - `detail`: 個人情報・秘密を含めない。禁止キーがあれば `RuntimeError`
    """
    forbidden = find_forbidden_key(detail)
    if forbidden is not None:
        raise RuntimeError(f"監査ログの detail に入れてはいけないキーです: {forbidden}")
    log = AuditLog(
        actor_type=ActorType.staff,
        actor_id=staff.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
    )
    if detail is not None:
        log.detail = detail
    session.add(log)
    await session.flush()
