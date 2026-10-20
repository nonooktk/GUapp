"""会話の読み書き（DS-TBL-24・25、DS-PRC-029-1・029-4）と、候補プール用の商品の読み出し。

- 往復数の予約・解放は条件付き UPDATE の 1 文（DS-DEC-98）。同じセッションへの同時要求は
  この UPDATE の行ロックで直列化され、2 つ目は更新行 0 になる
- ロックの順序は常に「chat_sessions → chat_messages」（5.5）
- 公開商品の条件は `products.published_filter()` の 1 か所を通す（B7）
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import CatalogEntry
from app.models import (
    Category,
    ChatMessage,
    ChatRole,
    ChatSession,
    Product,
    ProductCategory,
    Variant,
)
from app.repositories.products import (
    ProductSummary,
    published_filter,
    rows_to_summaries,
    summary_select,
)

# ── セッション ──


async def get_session_by_hash(session: AsyncSession, token_hash: str) -> ChatSession | None:
    stmt = select(ChatSession).where(ChatSession.token_hash == token_hash)
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_session(session: AsyncSession, token_hash: str) -> ChatSession:
    row = ChatSession(token_hash=token_hash, turns=0)
    session.add(row)
    await session.flush()
    return row


async def reserve_turn(session: AsyncSession, chat_session_id: int, limit: int) -> bool:
    """`UPDATE … SET turns = turns + 1 WHERE id = :id AND turns < :limit`。更新行 0 なら False。"""
    result = await session.execute(
        update(ChatSession)
        .where(ChatSession.id == chat_session_id, ChatSession.turns < limit)
        .values(turns=ChatSession.turns + 1)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1  # type: ignore[attr-defined]


async def release_turn(session: AsyncSession, chat_session_id: int) -> bool:
    """LLM が失敗したときに往復数を 1 戻す。`turns > 0` のときだけ減らす。"""
    result = await session.execute(
        update(ChatSession)
        .where(ChatSession.id == chat_session_id, ChatSession.turns > 0)
        .values(turns=ChatSession.turns - 1)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1  # type: ignore[attr-defined]


async def get_turns(session: AsyncSession, chat_session_id: int) -> int:
    stmt = select(ChatSession.turns).where(ChatSession.id == chat_session_id)
    return int((await session.execute(stmt)).scalar_one())


async def mark_handoff(session: AsyncSession, chat_session_id: int, now: datetime) -> None:
    """範囲外の案内を最初に出した時刻を入れる（`handoff_at` が NULL のときだけ）。"""
    await session.execute(
        update(ChatSession)
        .where(ChatSession.id == chat_session_id, ChatSession.handoff_at.is_(None))
        .values(handoff_at=now)
        .execution_options(synchronize_session=False)
    )


# ── メッセージ ──


async def add_message(
    session: AsyncSession,
    chat_session_id: int,
    role: ChatRole,
    body_masked: str,
    *,
    product_ids: list[int] | None = None,
    intent: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> ChatMessage:
    row = ChatMessage(
        chat_session_id=chat_session_id,
        role=role,
        body_masked=body_masked,
        product_ids=product_ids,
        intent=intent,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    session.add(row)
    await session.flush()
    return row


async def list_history(
    session: AsyncSession, chat_session_id: int, *, before_message_id: int, limit: int
) -> list[tuple[ChatRole, str]]:
    """直近 `limit` メッセージ（今回の分は除く）を時系列の順で返す。"""
    stmt = (
        select(ChatMessage.role, ChatMessage.body_masked)
        .where(ChatMessage.chat_session_id == chat_session_id, ChatMessage.id < before_message_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(ChatRole(r.role), r.body_masked) for r in reversed(rows)]


async def count_user_messages_since(session: AsyncSession, since: datetime) -> int:
    """日次上限の数え上げ（5.3）。`since` は今日（JST）の 0 時を UTC にした値。"""
    stmt = (
        select(func.count())
        .select_from(ChatMessage)
        .where(ChatMessage.role == ChatRole.user, ChatMessage.created_at >= since)
    )
    return int((await session.execute(stmt)).scalar_one())


# ── 候補プール・商品カード ──


async def list_catalog_entries(
    session: AsyncSession, *, limit: int | None = None, product_id: int | None = None
) -> list[CatalogEntry]:
    """公開商品を id 昇順で `limit` 件（`product_id` 指定ならその 1 件）。

    在庫は variants の合計が 1 以上かどうか。性別・種類は最小 id のカテゴリから取る。
    """
    stmt = select(Product).where(published_filter()).order_by(Product.id)
    if product_id is not None:
        stmt = stmt.where(Product.id == product_id)
    if limit is not None:
        stmt = stmt.limit(limit)
    products = list((await session.execute(stmt)).scalars().all())
    if not products:
        return []
    ids = [p.id for p in products]

    colors: dict[int, list[str]] = {}
    sizes: dict[int, list[str]] = {}
    stock: dict[int, int] = {}
    variant_rows = await session.execute(
        select(Variant.product_id, Variant.color, Variant.size, Variant.stock)
        .where(Variant.product_id.in_(ids))
        .order_by(Variant.product_id, Variant.id)
    )
    for pid, color, size, qty in variant_rows.all():
        if color not in colors.setdefault(pid, []):
            colors[pid].append(color)
        if size not in sizes.setdefault(pid, []):
            sizes[pid].append(size)
        stock[pid] = stock.get(pid, 0) + int(qty)

    genders: dict[int, tuple[str, str]] = {}
    category_rows = await session.execute(
        select(ProductCategory.product_id, Category.gender, Category.kind)
        .join(Category, Category.id == ProductCategory.category_id)
        .where(ProductCategory.product_id.in_(ids))
        .order_by(ProductCategory.product_id, Category.id)
    )
    for pid, gender, kind in category_rows.all():
        genders.setdefault(pid, (str(getattr(gender, "value", gender)), kind or ""))

    return [
        CatalogEntry(
            id=p.id,
            name=p.name,
            gender=genders.get(p.id, ("", ""))[0],
            kind=genders.get(p.id, ("", ""))[1],
            price_incl_tax=p.price_incl_tax,
            colors=tuple(colors.get(p.id, ())),
            sizes=tuple(sizes.get(p.id, ())),
            in_stock=stock.get(p.id, 0) > 0,
            material=p.material,
        )
        for p in products
    ]


async def get_product_cards(
    session: AsyncSession, product_ids: list[int]
) -> dict[int, ProductSummary]:
    """商品カード用の再取得（公開商品のみ。名称・税込価格・先頭画像・在庫切れは DB の値）。"""
    if not product_ids:
        return {}
    rows = (await session.execute(summary_select().where(Product.id.in_(product_ids)))).all()
    return {s.id: s for s in rows_to_summaries(rows)}
