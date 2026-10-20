"""初期データ投入（設計仕様書 5.3・プラン 5 章「seed の冪等性」、P2 追補b 5.8・DS-DEC-87）。

    uv run python -m app.seed            # products に行があれば何もしない（データ保護側）
    uv run python -m app.seed --reset    # 全 23 表を TRUNCATE してから投入（確認あり）
    uv run python -m app.seed --reset --yes
    uv run python -m app.seed --only-p2b # 会員・店舗・レビューだけを、各表が空のときに限って投入
    uv run python -m app.seed --only-p2c # 管理者（staff）だけを、表が空のときに限って投入
    uv run python -m app.seed --only-p2c --update-staff-password  # 管理者のパスワードだけ更新

`--only-p2b`・`--only-p2c` は、P1・P2-a の seed が入った共用の講義 DB へ P2-b・P2-c の seed だけを
足す手段（共用 DB では `--reset` を使わない。ADR-0002）。`--only-p2b` は商品（products）が
先に入っている必要がある。

管理者の seed（P2 追補c 5.7・DS-DEC-112）: login_id は `demo-staff`（環境変数
`SEED_STAFF_LOGIN_ID` で置き換え）、パスワードは `seed_data.DEMO_STAFF_PASSWORD`（ダミー値。環境変数
`SEED_STAFF_PASSWORD` で置き換え）。`APP_ENV=production` では `SEED_STAFF_PASSWORD` が必須で
12 文字以上、無ければ管理者を入れない。

接続先は環境変数 `DATABASE_URL`（`app.core.config`）。Alembic のマイグレーションとは分離し、
schema は先に `alembic upgrade head` で作っておく（本モジュールは DDL を発行しない）。
定義データは `app.seed_data`。個人情報は入れない。
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app import seed_data
from app.core.config import Settings, get_settings
from app.core.db import build_engine
from app.models import (
    ALL_TABLES,
    P1_TABLES,
    P2A_TABLES,
    P2B_TABLES,
    P2D_TABLES,
    Category,
    Content,
    ContentKind,
    Gender,
    Member,
    Product,
    ProductCategory,
    ProductImage,
    Review,
    ReviewFit,
    Staff,
    Store,
    SystemSetting,
    Variant,
)
from app.services.admin_auth import is_valid_login_id, normalize_login_id

# TRUNCATE の順（FK の子 → 親）。FOREIGN_KEY_CHECKS=0 で囲うが、順も守っておく
TRUNCATE_ORDER: tuple[str, ...] = (
    "payments",
    "order_items",
    "orders",
    "cart_items",
    "carts",
    "product_images",
    "product_categories",
    "variants",
    "products",
    "categories",
    "system_settings",
    "audit_logs",
)
assert set(TRUNCATE_ORDER) == set(P1_TABLES), "TRUNCATE_ORDER は P1 の 12 表と一致させる"

# P2-a で追加した表（DS-TBL-22 contents）。他表への FK を持たないため順は問わない
CONTENT_TRUNCATE_ORDER: tuple[str, ...] = ("contents",)
assert set(CONTENT_TRUNCATE_ORDER) == set(P2A_TABLES), "P2A_TABLES と一致させる"

# P2-b で追加した 8 表（設計仕様書 P2 追補b 5.8）。子 → 親の順:
# email_tokens・restock_notifications・reviews・sessions・login_attempts は
# 会員・店舗・商品・バリエーションを参照する（または参照しない）子。members・stores・staff は親
P2B_CHILD_TRUNCATE_ORDER: tuple[str, ...] = (
    "email_tokens",
    "restock_notifications",
    "reviews",
    "sessions",
    "login_attempts",
)
P2B_PARENT_TRUNCATE_ORDER: tuple[str, ...] = ("members", "stores", "staff")
assert set(P2B_CHILD_TRUNCATE_ORDER + P2B_PARENT_TRUNCATE_ORDER) == set(P2B_TABLES), (
    "P2B_TABLES と一致させる"
)

# P2-d で追加した表（DS-TBL-24・25）。子（chat_messages）→ 親（chat_sessions）の順
CHAT_TRUNCATE_ORDER: tuple[str, ...] = ("chat_messages", "chat_sessions")
assert set(CHAT_TRUNCATE_ORDER) == set(P2D_TABLES), "P2D_TABLES と一致させる"

# 全表を空にする順（子 → 親）。チャット（chat_messages → chat_sessions。他表への FK なし）→
# P2-b の子 → P1（orders などの子 → 親）→ P2-a → P2-b の親
FULL_TRUNCATE_ORDER: tuple[str, ...] = (
    CHAT_TRUNCATE_ORDER
    + P2B_CHILD_TRUNCATE_ORDER
    + TRUNCATE_ORDER
    + CONTENT_TRUNCATE_ORDER
    + P2B_PARENT_TRUNCATE_ORDER
)
assert set(FULL_TRUNCATE_ORDER) == set(ALL_TABLES), "FULL_TRUNCATE_ORDER は全 23 表と一致させる"

COUNT_TABLES: tuple[str, ...] = (
    "categories",
    "products",
    "variants",
    "product_images",
    "product_categories",
    "system_settings",
    "contents",
    "members",
    "stores",
    "reviews",
    "staff",
)


@dataclass(frozen=True)
class SeedResult:
    skipped: bool  # True なら既存データがあり何もしなかった
    counts: dict[str, int]  # 実行後の件数（COUNT_TABLES）
    # 補足（例: production で SEED_MEMBER_PASSWORD が無く会員の seed を行わなかった）
    notes: tuple[str, ...] = ()


def _hash_password(password: str) -> str:
    """seed 会員用の argon2id ハッシュ（DS-DEC-68 と同じパラメータ）。

    `app/core/passwords.py`（レーン B）ができたら、そちらの `hash_password` に寄せてよい。
    パラメータは必ず揃える（time_cost=2・memory_cost=19456・parallelism=1）。
    """
    return PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1).hash(password)


def member_seed_password(settings: Settings) -> str | None:
    """seed 会員のパスワードを決める（DS-DEC-87）。None なら会員の seed を行わない。

    - 環境変数 `SEED_MEMBER_PASSWORD` があればそれを使う
    - `APP_ENV=production` で無ければ None（既知のパスワードの会員を公開環境に残さない）
    - それ以外（開発・テスト）は `seed_data.DEMO_MEMBER_PASSWORD`
    """
    explicit = settings.SEED_MEMBER_PASSWORD
    if explicit:
        return explicit
    if settings.is_production:
        return None
    return seed_data.DEMO_MEMBER_PASSWORD


@dataclass(frozen=True)
class StaffSeedCredentials:
    """seed する管理者の login_id（正規化済み）と、NFKC 正規化済みのパスワード。"""

    login_id: str
    password: str


def staff_seed_credentials(settings: Settings) -> tuple[StaffSeedCredentials | None, str | None]:
    """seed する管理者の資格情報を決める（DS-DEC-112）。`(資格情報, 投入しない理由)`。

    - login_id: 環境変数 `SEED_STAFF_LOGIN_ID`、無ければ `seed_data.STAFF[0].login_id`。
      NFKC・小文字化のあと DS-API-050 の形式に合わないときは投入しない
    - パスワード: 環境変数 `SEED_STAFF_PASSWORD` があればそれ、無ければ
      `seed_data.DEMO_STAFF_PASSWORD`。ハッシュ化の前に NFKC 正規化する（ログインの検証と同じ）
    - `APP_ENV=production` では `SEED_STAFF_PASSWORD` が必須で、NFKC 正規化後に 12 文字以上。
      無い・短いときは投入しない（既知のパスワードの管理者を公開環境に残さない。点検の B-07）
    """
    raw_login_id = settings.SEED_STAFF_LOGIN_ID.strip() or seed_data.STAFF[0].login_id
    if not is_valid_login_id(raw_login_id):
        return None, "SEED_STAFF_LOGIN_ID の形式が正しくないため、管理者の seed を行いません"
    login_id = normalize_login_id(raw_login_id)

    explicit = unicodedata.normalize("NFKC", settings.SEED_STAFF_PASSWORD)
    if settings.is_production:
        if len(explicit) < seed_data.STAFF_PASSWORD_MIN_LENGTH_PRODUCTION:
            return None, (
                "APP_ENV=production で SEED_STAFF_PASSWORD が無い、または"
                f" {seed_data.STAFF_PASSWORD_MIN_LENGTH_PRODUCTION} 文字未満のため、"
                "管理者の seed を行いません"
            )
        return StaffSeedCredentials(login_id, explicit), None
    if explicit:
        return StaffSeedCredentials(login_id, explicit), None
    return StaffSeedCredentials(login_id, seed_data.DEMO_STAFF_PASSWORD), None


async def count_rows(
    conn: AsyncConnection, tables: tuple[str, ...] = COUNT_TABLES
) -> dict[str, int]:
    """件数を数える。表名は ALL_TABLES（全 23 表）に限定して SQL に埋め込む（外部入力は不可）。"""
    out: dict[str, int] = {}
    for name in tables:
        if name not in ALL_TABLES:
            raise ValueError(f"既知の表ではありません: {name}")
        out[name] = int((await conn.execute(text(f"SELECT COUNT(*) FROM `{name}`"))).scalar_one())
    return out


async def truncate_all_tables(conn: AsyncConnection) -> None:
    """全 23 表（ALL_TABLES。P1 の 12 表 + P2-a の contents + P2-b の 8 表 + P2-d のチャット 2 表）
    を空にする。

    --reset とテストの後片付け用。順序は `FULL_TRUNCATE_ORDER`（子 → 親）。`FOREIGN_KEY_CHECKS=0`
    で囲う方式は変えない。P2-a で contents が増えたため、関数名を中身（全表を対象にする）に
    合わせて改名した（旧名 `truncate_p1_tables`）。
    """
    await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
    try:
        for name in FULL_TRUNCATE_ORDER:
            await conn.execute(text(f"TRUNCATE TABLE `{name}`"))
    finally:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


async def _table_is_empty(session: AsyncSession, model: type) -> bool:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one() == 0


async def _product_ids_by_number(session: AsyncSession) -> dict[int, int]:
    """商品番号 → products.id。名前で引く（`--only-p2b` で既存の商品に reviews を紐づける用）。

    seed の商品名は一意（UT-SEED-12 で確認）。見つからない番号があれば ValueError。
    """
    rows = (await session.execute(select(Product.id, Product.name))).all()
    by_name = {name: pid for pid, name in rows}
    out: dict[int, int] = {}
    for p in seed_data.PRODUCTS:
        if p.name not in by_name:
            raise ValueError(
                "reviews を投入できません: 商品が見つかりません"
                f"（番号 {p.number}）。先に P1 の seed を投入してください"
            )
        out[p.number] = by_name[p.name]
    return out


async def _insert_p2b(
    session: AsyncSession, product_ids: dict[int, int] | None = None
) -> tuple[dict[str, int], list[str]]:
    """P2-b の seed（members・stores・reviews。DS-DEC-87）。各表が空のときに限って投入する。

    戻り値は (投入した件数, 補足)。`product_ids`（商品番号 → ID）が None なら商品名で引く。
    会員は `member_seed_password` が None（production で `SEED_MEMBER_PASSWORD` 無し）なら入れない。
    """
    inserted = {"members": 0, "stores": 0, "reviews": 0}
    notes: list[str] = []

    if await _table_is_empty(session, Member):
        password = member_seed_password(get_settings())
        if password is None:
            notes.append(
                "APP_ENV=production で SEED_MEMBER_PASSWORD が無いため、会員の seed を行いません"
            )
        else:
            now = datetime.now(UTC).replace(tzinfo=None)
            for m in seed_data.MEMBERS:
                session.add(
                    Member(
                        email=m.email,
                        password_hash=_hash_password(password),
                        name=m.name,
                        personalize_opt_in=False,
                        email_verified_at=now if m.email_verified else None,
                    )
                )
                inserted["members"] += 1

    if await _table_is_empty(session, Store):
        for st in seed_data.STORES:
            session.add(
                Store(
                    code=st.code,
                    name=st.name,
                    prefecture=st.prefecture,
                    postal_code=st.postal_code,
                    address=st.address,
                    pickup_enabled=st.pickup_enabled,
                    sort_order=st.sort_order,
                )
            )
            inserted["stores"] += 1

    if await _table_is_empty(session, Review):
        ids = product_ids if product_ids is not None else await _product_ids_by_number(session)
        for r in seed_data.REVIEWS:
            session.add(
                Review(
                    product_id=ids[r.product_number],
                    member_id=r.member_id,
                    rating=r.rating,
                    body=r.body,
                    fit=ReviewFit(r.fit) if r.fit else None,
                    approved=r.approved,
                )
            )
            inserted["reviews"] += 1

    await session.flush()
    return inserted, notes


def _warn(message: str) -> None:
    """管理者の seed を行わなかった理由を標準エラーに出す（DS-DEC-112）。

    `SeedResult.notes` には入れない（P2-b の会員の seed の補足と混ぜず、他の seed は続ける）。
    """
    print(f"[seed] 注意: {message}", file=sys.stderr)


async def _insert_p2c(session: AsyncSession) -> dict[str, int]:
    """P2-c の seed（staff 1 件。DS-DEC-112）。`staff` が空のときに限って投入する。

    資格情報が決まらない（production で `SEED_STAFF_PASSWORD` が無い・短い、login_id の形式不正）
    ときは投入せず、理由を標準エラーに出す（他の seed は続ける）。
    """
    inserted = {"staff": 0}
    if await _table_is_empty(session, Staff):
        creds, reason = staff_seed_credentials(get_settings())
        if creds is None:
            _warn(reason or "管理者の seed を行いません")
        else:
            session.add(
                Staff(
                    login_id=creds.login_id,
                    password_hash=_hash_password(creds.password),
                    role=seed_data.STAFF[0].role,
                )
            )
            inserted["staff"] = 1
    await session.flush()
    return inserted


async def _update_staff_password(session: AsyncSession) -> int:
    """`--update-staff-password`: 同じ login_id の行のパスワードのハッシュだけを更新する。

    更新した件数を返す。更新しなかった理由は標準エラーに出す。
    """
    creds, reason = staff_seed_credentials(get_settings())
    if creds is None:
        _warn(reason or "管理者のパスワードを更新しません")
        return 0
    result = await session.execute(
        update(Staff)
        .where(Staff.login_id == creds.login_id)
        .values(password_hash=_hash_password(creds.password))
    )
    if result.rowcount == 0:
        _warn("同じ login_id の管理者がいないため、パスワードを更新しませんでした")
        return 0
    return int(result.rowcount)


async def _insert_all(session: AsyncSession) -> list[str]:
    # categories（親 → 子。slug → id を控える）
    category_ids: dict[str, int] = {}
    for c in seed_data.CATEGORIES:
        row = Category(
            name=c.name,
            slug=c.slug,
            gender=Gender(c.gender),
            sort_order=c.sort_order,
            kind=c.kind,
            parent_id=category_ids[c.parent_slug] if c.parent_slug else None,
        )
        session.add(row)
        await session.flush()
        category_ids[c.slug] = row.id

    # products ＋ 画像 ＋ カテゴリ割当
    product_ids: dict[int, int] = {}
    for i, p in enumerate(seed_data.PRODUCTS):
        row = Product(
            name=p.name,
            description=f"{p.name}。{p.material}。",
            material=p.material,
            price_incl_tax=p.price_incl_tax,
            published=p.published,
            sort_order=i,
        )
        session.add(row)
        await session.flush()
        product_ids[p.number] = row.id
        session.add(ProductImage(product_id=row.id, path=p.image_path, sort_order=0))
        session.add(ProductCategory(product_id=row.id, category_id=category_ids[p.category_slug]))

    # variants（在庫は seed 固定の乱数。テスト用 SKU は固定値）
    rng = random.Random(seed_data.STOCK_RANDOM_SEED)
    for v in seed_data.build_variants(rng):
        session.add(
            Variant(
                product_id=product_ids[v.product_number],
                color=v.color,
                size=v.size,
                sku=v.sku,
                stock=v.stock,
            )
        )

    # system_settings
    for key, value, description in seed_data.SYSTEM_SETTINGS:
        session.add(SystemSetting(key=key, value=value, description=description))

    # contents（P2-a・DS-TBL-22）。publish_from/to は seed 実行時刻からの相対値（設計仕様書 5.2）
    now = datetime.now(UTC).replace(tzinfo=None)
    for c in seed_data.CONTENTS:
        publish_to = (
            now + timedelta(days=c.publish_to_offset_days)
            if c.publish_to_offset_days is not None
            else None
        )
        session.add(
            Content(
                kind=ContentKind(c.kind),
                slug=c.slug,
                title=c.title,
                body=c.body,
                publish_from=now + timedelta(days=c.publish_from_offset_days),
                publish_to=publish_to,
                sort_order=c.sort_order,
            )
        )

    await session.flush()

    # P2-b: 会員・店舗・レビュー（DS-DEC-87）
    _, notes = await _insert_p2b(session, product_ids)
    # P2-c: 管理者（DS-DEC-112）。投入しない理由は標準エラーに出す（`notes` には入れない）
    await _insert_p2c(session)
    return notes


async def seed(
    engine: AsyncEngine,
    *,
    reset: bool = False,
    only_p2b: bool = False,
    only_p2c: bool = False,
    update_staff_password: bool = False,
) -> SeedResult:
    """seed を投入する。

    - `reset=False`（既定）: products に 1 行でもあれば何もせず `skipped=True` を返す
    - `reset=True`: 全 23 表を TRUNCATE してから投入
    - `only_p2b=True`: 会員・店舗・レビューだけを、各表が空のときに限って投入する
      （2 回目は何もしない。`reset` とは併用できない）。投入が 0 件なら `skipped=True`
    - `only_p2c=True`: 管理者（staff）だけを、表が空のときに限って投入する（2 回目は何もしない）。
      `update_staff_password=True` を足すと、同じ login_id の行のパスワードのハッシュだけを更新する
      （他の列は変えない）。`reset`・`only_p2b` とは併用できない
    """
    if sum((reset, only_p2b, only_p2c)) > 1:
        raise ValueError("reset・only_p2b・only_p2c は併用できません")
    if update_staff_password and not only_p2c:
        raise ValueError("update_staff_password は only_p2c とだけ併用できます")

    if only_p2c:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            if update_staff_password:
                changed = await _update_staff_password(session)
            else:
                changed = sum((await _insert_p2c(session)).values())
            await session.commit()
        async with engine.connect() as conn:
            return SeedResult(skipped=changed == 0, counts=await count_rows(conn))

    if only_p2b:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            inserted, notes = await _insert_p2b(session)
            await session.commit()
        async with engine.connect() as conn:
            return SeedResult(
                skipped=sum(inserted.values()) == 0,
                counts=await count_rows(conn),
                notes=tuple(notes),
            )

    if reset:
        async with engine.begin() as conn:
            await truncate_all_tables(conn)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        existing = (await session.execute(select(func.count()).select_from(Product))).scalar_one()
        if existing > 0:
            async with engine.connect() as conn:
                return SeedResult(skipped=True, counts=await count_rows(conn))
        notes = await _insert_all(session)
        await session.commit()

    async with engine.connect() as conn:
        return SeedResult(skipped=False, counts=await count_rows(conn), notes=tuple(notes))


def _format_counts(counts: dict[str, int]) -> str:
    return " / ".join(f"{k}={v}" for k, v in counts.items())


def _database_name(url: str) -> str:
    return (make_url(url).database or "").split("?")[0]


async def _amain(args: argparse.Namespace) -> int:
    settings = get_settings()
    url = settings.DATABASE_URL
    if not url:
        print("DATABASE_URL が未設定です（環境変数で与えてください）", file=sys.stderr)
        return 2
    db_name = _database_name(url)

    if args.reset and not args.yes:
        answer = input(
            f"DB '{db_name}' の全 23 表（P1・P2-a・P2-b・P2-d）を TRUNCATE して"
            " seed を投入します。続けますか？ [y/N]: "
        )
        if answer.strip().lower() not in {"y", "yes"}:
            print("中止しました（何も変更していません）")
            return 1

    # DB_POOL_SIZE・DB_MAX_OVERFLOW（DS-DEC-46）を尊重する。共用の講義サーバーに
    # 対しては 5／5 を渡すことで、seed 実行時も接続数を絞れる
    engine = build_engine(
        url, pool_size=settings.DB_POOL_SIZE, max_overflow=settings.DB_MAX_OVERFLOW
    )
    try:
        result = await seed(
            engine,
            reset=args.reset,
            only_p2b=args.only_p2b,
            only_p2c=args.only_p2c,
            update_staff_password=args.update_staff_password,
        )
    finally:
        await engine.dispose()

    if args.only_p2c and args.update_staff_password:
        if result.skipped:
            print(f"[seed] DB '{db_name}': 管理者のパスワードは更新しませんでした")
        else:
            print(f"[seed] DB '{db_name}': 管理者のパスワードを更新しました")
    elif result.skipped and args.only_p2c:
        print(
            f"[seed] DB '{db_name}': 管理者の表が空ではない、または投入できないため"
            f"何もしませんでした（{_format_counts(result.counts)}）"
        )
    elif result.skipped and args.only_p2b:
        print(
            f"[seed] DB '{db_name}': 会員・店舗・レビューの表がすべて空ではないため"
            f"何もしませんでした（{_format_counts(result.counts)}）"
        )
    elif result.skipped:
        print(
            f"[seed] DB '{db_name}': 既に products に行があるため何もしませんでした"
            f"（{_format_counts(result.counts)}）。投入し直すには --reset を付けてください"
        )
    else:
        print(f"[seed] DB '{db_name}': 投入完了（{_format_counts(result.counts)}）")
    for note in result.notes:
        print(f"[seed] 注意: {note}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GUapp 初期データ投入")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="全 23 表（P1・P2-a・P2-b・P2-d）を TRUNCATE してから投入する（破壊的）",
    )
    parser.add_argument(
        "--only-p2b",
        action="store_true",
        help="会員・店舗・レビューだけを、各表が空のときに限って投入する（--reset とは併用不可）",
    )
    parser.add_argument(
        "--only-p2c",
        action="store_true",
        help="管理者（staff）だけを、表が空のときに限って投入する（他の --reset 等とは併用不可）",
    )
    parser.add_argument(
        "--update-staff-password",
        action="store_true",
        help="--only-p2c と併用: 同じ login_id の管理者のパスワードのハッシュだけを更新する",
    )
    parser.add_argument("--yes", action="store_true", help="--reset の確認プロンプトを省略する")
    args = parser.parse_args(argv)
    if sum((args.reset, args.only_p2b, args.only_p2c)) > 1:
        parser.error("--reset・--only-p2b・--only-p2c は併用できません")
    if args.update_staff_password and not args.only_p2c:
        parser.error("--update-staff-password は --only-p2c と一緒に指定してください")
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
