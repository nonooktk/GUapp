"""UT-RESTOCK-01〜03 再入荷通知（DS-DEC-80・DS-PRC-007・007a）。SQLite インメモリ。

申込の upsert（MySQL 専用の構文）と、同時実行・ロックは IT-007・007a で確かめる。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import AuditLog, Base, Product, RestockNotification, Variant
from app.repositories import restock as restock_repo
from app.services.restock import PENDING_LIMIT, is_over_limit, notify_restock
from tests.recording_mail import RecordingMailAdapter


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def _variants(session: AsyncSession, n: int, stock: int = 0) -> list[int]:
    product = Product(name="リブレギンス", price_incl_tax=990, published=True)
    session.add(product)
    await session.flush()
    variants = [
        Variant(product_id=product.id, color="黒", size=f"S{i}", sku=f"T-{i}", stock=stock)
        for i in range(n)
    ]
    session.add_all(variants)
    await session.flush()
    return [v.id for v in variants]


def _apply(variant_id: int, email: str, *, notified: bool = False) -> RestockNotification:
    from datetime import datetime

    return RestockNotification(
        variant_id=variant_id, email=email, notified_at=datetime(2026, 10, 1) if notified else None
    )


# ── UT-RESTOCK-01 申込の上限 ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("pending_other", "over"), [(0, False), (8, False), (9, False), (10, True), (11, True)]
)
def test_ut_restock_01_limit_boundary(pending_other: int, over: bool) -> None:
    assert PENDING_LIMIT == 10
    assert is_over_limit(pending_other) is over


async def test_ut_restock_01_resubmission_to_an_existing_variant_is_not_counted(
    session: AsyncSession,
) -> None:
    ids = await _variants(session, 12)
    email = "a@example.com"
    # 未通知が 9・10・11 件の状態を作り、「今回の variant を除く件数」で判定する
    for count in (9, 10, 11):
        await session.execute(RestockNotification.__table__.delete())
        session.add_all([_apply(v, email) for v in ids[:count]])
        await session.flush()
        new_variant = ids[11]  # 未申込の variant
        over_new = is_over_limit(
            await restock_repo.count_pending_for_email(
                session, email, exclude_variant_id=new_variant
            )
        )
        assert over_new is (count >= 10), count
        # 既に申し込んだ variant への再申込は、自分を除いて数えるので 10 件までは可
        again = is_over_limit(
            await restock_repo.count_pending_for_email(session, email, exclude_variant_id=ids[0])
        )
        assert again is (count - 1 >= 10), count


async def test_ut_restock_01_notified_rows_and_other_emails_are_not_pending(
    session: AsyncSession,
) -> None:
    ids = await _variants(session, 4)
    session.add_all(
        [
            _apply(ids[0], "a@example.com"),
            _apply(ids[1], "a@example.com", notified=True),  # 通知済み
            _apply(ids[2], "b@example.com"),  # 別のメール
        ]
    )
    await session.flush()
    assert await restock_repo.count_pending_for_email(session, "a@example.com") == 1


# ── UT-RESTOCK-02 通知対象の選択 ─────────────────────────────────────────────


async def test_ut_restock_02_only_unnotified_rows_are_claimed(session: AsyncSession) -> None:
    from datetime import datetime

    ids = await _variants(session, 2)
    session.add_all(
        [_apply(ids[0], f"u{i}@example.com") for i in range(3)]
        + [_apply(ids[0], f"n{i}@example.com", notified=True) for i in range(2)]
        + [_apply(ids[1], "other@example.com")]  # 別の variant
    )
    await session.flush()
    claimed = await restock_repo.claim_unnotified(session, ids[0], datetime(2026, 10, 20))
    assert sorted(email for _, email in claimed) == [f"u{i}@example.com" for i in range(3)]
    # 確保した 3 行は notified_at が入り、別の variant の行は NULL のまま
    nulls = (
        await session.execute(select(func.count()).where(RestockNotification.notified_at.is_(None)))
    ).scalar_one()
    assert nulls == 1
    assert await restock_repo.claim_unnotified(session, ids[0], datetime(2026, 10, 20)) == []


# ── UT-RESTOCK-03 ログ・監査にメールを残さない ───────────────────────────────


class _FailsOnSecond(RecordingMailAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def send_restock_notice(self, to, product_name, color, size, url) -> None:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError(f"smtp rejected {to}")
        await super().send_restock_notice(to, product_name, color, size, url)


async def test_ut_restock_03_logs_and_audit_detail_never_contain_the_address(
    session: AsyncSession,
    app_env: Callable[..., None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    app_env(PUBLIC_WEB_BASE_URL="http://localhost:3000")
    (vid,) = await _variants(session, 1)
    emails = ["alice@example.com", "bob@example.com", "carol@example.com"]
    session.add_all([_apply(vid, e) for e in emails])
    await session.flush()
    await session.execute(update(Variant).where(Variant.id == vid).values(stock=5))
    await session.commit()

    mail = _FailsOnSecond()
    with caplog.at_level(logging.DEBUG):
        sent = await notify_restock(session, vid, mail=mail)
    assert sent == 2 and len(mail.sent) == 2

    logs = "\n".join(r.getMessage() for r in caplog.records)
    audits = (await session.execute(select(AuditLog.action, AuditLog.detail))).all()
    assert {a for a, _ in audits} == {"restock.notified", "restock.mail_failed"}
    dumped = logs + json.dumps([d for _, d in audits])
    for email in emails:
        assert email not in dumped
    assert "@" not in json.dumps([d for _, d in audits]), "audit_logs の detail にメールを残さない"
    details = {a: d for a, d in audits}
    assert details["restock.mail_failed"] == {"count": 1}
    assert details["restock.notified"] == {"count": 2}


def test_restock_cli_refuses_to_run_in_production(
    app_env: Callable[..., None], capsys: pytest.CaptureFixture[str]
) -> None:
    """手動確認用 CLI は `APP_ENV=production` では実行を拒否する（DS-PRC-007a）。"""
    from app import restock_notify

    app_env(APP_ENV="production")
    assert restock_notify.main(["--sku", "GU-029-BK-M"]) == restock_notify.EXIT_REFUSED
    assert "production" in capsys.readouterr().err
