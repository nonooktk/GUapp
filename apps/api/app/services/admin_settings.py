"""管理：設定の処理（DS-PRC-052。設計仕様書 P2 追補c 4.3・4.6・5.4・DS-DEC-119）。

担当レーン: C-2（ADR-0006 の削る順番の④。商品・在庫とは別ファイル）。

更新できるのは `tax_rate`・`shipping_fee`・`free_shipping_threshold` の 3 つ。
`payment_timeout_minutes` は表示のみ。複数のキーは 1 トランザクションで、1 つでも失敗したら
全体を更新しない。公開側（`GET /settings/public`・金額計算）は毎回 DB を読むため、次のアクセスから
反映される。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_session import CurrentStaff
from app.core.errors import AppError, internal_error
from app.repositories import admin_settings as repo
from app.schemas.admin_settings import (
    AdminSettingItemOut,
    AdminSettingsOut,
    SettingsUpdateIn,
    SettingsUpdateOut,
)
from app.services.admin_audit import ACTION_SETTINGS_UPDATE, write_admin_audit
from app.services.optimistic import ensure_expected
from app.services.pricing import tax_rate_basis_points

logger = logging.getLogger("app.services.admin_settings")

# 業務の範囲（DS-DEC-119。意見として置いた値）
TAX_RATE_MIN_BP = 0
TAX_RATE_MAX_BP = 30
TAX_RATE_MIN_TEXT = "0.00"
TAX_RATE_MAX_TEXT = "0.30"
SHIPPING_FEE_MIN = 0
SHIPPING_FEE_MAX = 5000
FREE_SHIPPING_THRESHOLD_MIN = 0
FREE_SHIPPING_THRESHOLD_MAX = 100000


@dataclass(frozen=True)
class _Spec:
    key: str
    label: str
    editable: bool
    unit: str | None
    min: str | int | None
    max: str | int | None


# 返す順序（DS-API-052）
SETTING_SPECS: tuple[_Spec, ...] = (
    _Spec("tax_rate", "消費税率", True, None, TAX_RATE_MIN_TEXT, TAX_RATE_MAX_TEXT),
    _Spec("shipping_fee", "送料", True, "円", SHIPPING_FEE_MIN, SHIPPING_FEE_MAX),
    _Spec(
        "free_shipping_threshold",
        "送料無料の下限",
        True,
        "円",
        FREE_SHIPPING_THRESHOLD_MIN,
        FREE_SHIPPING_THRESHOLD_MAX,
    ),
    _Spec("payment_timeout_minutes", "決済待ちの期限", False, "分", None, None),
)
ALL_KEYS: tuple[str, ...] = tuple(s.key for s in SETTING_SPECS)


def validate_setting_range(key: str, value: str | int) -> None:
    """業務の範囲。下限未満は 422 `unsupported_value`、上限超えは 422 `limit_exceeded`（`limit`）。

    `tax_rate` は `tax_rate_basis_points`（公開側の金額計算と同じ変換）で判定する。
    形（`^[0-9]\\.[0-9]{2}$`）は Pydantic 済みで、ここでは範囲だけ。
    """
    if key == "tax_rate":
        assert isinstance(value, str)
        bp = tax_rate_basis_points(value)
        if bp < TAX_RATE_MIN_BP:
            raise AppError(422, "unsupported_value", field=key)
        if bp > TAX_RATE_MAX_BP:
            raise AppError(422, "limit_exceeded", field=key, limit=TAX_RATE_MAX_TEXT)
        return
    low, high = {
        "shipping_fee": (SHIPPING_FEE_MIN, SHIPPING_FEE_MAX),
        "free_shipping_threshold": (FREE_SHIPPING_THRESHOLD_MIN, FREE_SHIPPING_THRESHOLD_MAX),
    }[key]
    assert isinstance(value, int)
    if value < low:
        raise AppError(422, "unsupported_value", field=key)
    if value > high:
        raise AppError(422, "limit_exceeded", field=key, limit=high)


def _check_stored(raw: dict[str, Any]) -> None:
    """キー欠落・型不正は設定の投入漏れ（運用事故）。500 にして詳細はログへ（DS-API-020 と同じ）"""
    missing = [k for k in ALL_KEYS if k not in raw]
    if missing:
        logger.error("system_settings にキーがありません: %s", missing)
        raise internal_error()
    tax = raw["tax_rate"]
    if not isinstance(tax, str):
        logger.error("system_settings.tax_rate が文字列ではありません（%s）", type(tax).__name__)
        raise internal_error()
    for key in ALL_KEYS[1:]:
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, int):
            logger.error("system_settings.%s が整数ではありません（%s）", key, type(value).__name__)
            raise internal_error()


def _items(raw: dict[str, Any]) -> list[AdminSettingItemOut]:
    return [
        AdminSettingItemOut(
            key=s.key,
            label=s.label,
            value=raw[s.key],
            editable=s.editable,
            unit=s.unit,
            min=s.min,
            max=s.max,
        )
        for s in SETTING_SPECS
    ]


async def get_settings(session: AsyncSession) -> AdminSettingsOut:
    """DS-API-052。4 件を決まった順で返す。キー欠落などは 500 `internal_error`。"""
    try:
        raw = await repo.fetch_values(session, ALL_KEYS)
    finally:
        await session.rollback()
    _check_stored(raw)
    return AdminSettingsOut(items=_items(raw))


async def update_settings(
    session: AsyncSession, staff: CurrentStaff, body: SettingsUpdateIn
) -> SettingsUpdateOut:
    requested = body.requested()
    try:
        # 2. 業務の範囲を、変更するすべてのキーについて先に検査（1 つでも外れたら何も更新しない）
        for key, (value, _expected) in requested.items():
            validate_setting_range(key, value)
        # 3. 変更するキーの行をキー名の昇順で FOR UPDATE。行が無ければ 500（投入漏れ）
        locked = await repo.lock_values(session, list(requested))
        missing = [k for k in requested if k not in locked]
        if missing:
            logger.error("system_settings にキーがありません: %s", missing)
            raise internal_error()
        # 4. キーごとに照合（表示の順。最初に不一致だったキーで 409）
        for key, (_value, expected) in requested.items():
            ensure_expected(key, expected, locked[key])
        # 5. 値が変わるキーだけ UPDATE
        changes = {
            key: (locked[key], value)
            for key, (value, _expected) in requested.items()
            if value != locked[key]
        }
        for key, (_before, after) in changes.items():
            await repo.set_value(session, key, after)
        # 応答用に 4 件を読む（自分の更新を含む）
        raw = await repo.fetch_values(session, ALL_KEYS)
        _check_stored(raw)
        if not changes:
            await session.rollback()
            return SettingsUpdateOut(items=_items(raw), changed=[])
        # 6. 監査ログ（変更したキーの前後の値。target_id は先頭のキー名）
        await write_admin_audit(
            session,
            staff,
            action=ACTION_SETTINGS_UPDATE,
            target_type="setting",
            target_id=next(iter(changes)),
            detail={key: {"before": b, "after": a} for key, (b, a) in changes.items()},
        )
        # 7. COMMIT
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    return SettingsUpdateOut(items=_items(raw), changed=list(changes))
