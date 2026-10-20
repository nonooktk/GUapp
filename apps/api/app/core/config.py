"""アプリ設定（pydantic-settings）。

値はすべて環境変数から読む（設計仕様書 8.2、`.env.example` のキー名と一致）。
秘匿値をコードに書かない（規定 §3）。
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]
LlmProvider = Literal["auto", "openai", "stub"]
ReasoningEffort = Literal["none", "low", "medium", "high"]
# スタブの動き（P2 追補d 8.4）。本番では無視される
StubScenario = Literal[
    "ok",
    "unknown_id",
    "out_of_pool",
    "price_tamper",
    "faq_number_tamper",
    "html",
    "canary",
    "timeout",
    "error",
    "refusal",
]


class Settings(BaseSettings):
    """環境変数から組み立てる設定。"""

    model_config = SettingsConfigDict(
        # .env はローカル開発の利便のために読むが、リポジトリには置かない（gitignore 済み）
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: AppEnv = "development"
    # 書式のみ: mysql+asyncmy://user:pass@host:3306/guapp  # pragma: allowlist secret
    DATABASE_URL: str = Field(default="", description="SQLAlchemy 接続 URL")
    # BFF → FastAPI の内部認証トークン（DS-DEC-27）
    INTERNAL_TOKEN: str = Field(default="", description="X-Internal-Token の期待値")
    # 許可オリジン（BFF の URL 1 つ。ワイルドカード禁止）
    CORS_ALLOW_ORIGIN: str = Field(default="", description="CORS 許可オリジン（1 つ）")
    # 決済スタブの結果（P1 のみ。未設定＝スタブ OFF。DS-DEC-26）
    PAYMENT_STUB_RESULT: Literal["ok", "ng"] | None = None
    # 商品画像の配信ベース URL（DS-DEC-22）
    IMAGE_BASE_URL: str = ""
    # テスト専用: 注文確定の金額照合と在庫引当の間に入れる待ち（ms）。
    # APP_ENV=test 以外では無視される（テスト設計書 1.4 #7）
    TEST_RESERVE_DELAY_MS: int = 0
    # DB 接続プール設定（設計仕様書追補 P2-a 8.5・DS-DEC-46）。
    # 既定値は現状どおり 20／10。共用の講義サーバーに繋ぐときだけ環境変数で絞る（推奨 5／5）
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    # Azure MySQL の CA 証明書ファイルの絶対パス（8.1 第2案・DS-DEC-42・45 で使用）。
    # 第1案（DATABASE_URL の ssl_ca クエリ）で接続できれば未設定のままでよい
    DB_SSL_CA_PATH: str = ""

    # ── P2-b（設計仕様書 P2 追補b 8.1）──────────────────────────────────────
    # メールのリンク（確認・再設定・再入荷）のホスト部。リクエストの `Host` ヘッダは使わない
    # （DS-DEC-75）。ローカルは `http://localhost:3000`。末尾の `/` は付けない。
    # 未設定のときは、リンクを含むメールを送る処理が 500 になる（設定漏れを黙って許さない）
    PUBLIC_WEB_BASE_URL: str = ""
    # 登録・再設定の要求・再入荷の申込で許すメールのドメイン（カンマ区切り、小文字化して
    # 完全一致。DS-DEC-88）。未設定は制限なし。判定は `demo_email_domains` を使う
    DEMO_EMAIL_DOMAINS: str = ""
    # seed の会員のパスワード（seed 実行時のみ。DS-DEC-87）。開発・テストは未設定でよい
    # （seed_data の定数を使う）。`APP_ENV=production` では必須で、無ければ会員の seed を行わない
    SEED_MEMBER_PASSWORD: str = ""

    # ── P2-c（設計仕様書 P2 追補c 8.1・DS-DEC-112）─────────────────────────────
    # seed の管理者のパスワード・login_id（seed 実行時のみ）。開発・テストは未設定でよい
    # （seed_data の定数を使う）。`APP_ENV=production` では `SEED_STAFF_PASSWORD` が必須で
    # 12 文字以上。無い、または短ければ管理者の seed を行わない（管理画面にログインできない状態）
    SEED_STAFF_PASSWORD: str = ""
    SEED_STAFF_LOGIN_ID: str = ""

    # ── F-029 AI アシスタント（設計仕様書 P2 追補d 8.1。範囲外の値は起動時に例外）──
    # OpenAI のキー。空ならスタブ（開発・テスト）または無効（本番）。repr に出さない
    OPENAI_API_KEY: str = Field(default="", repr=False)
    OPENAI_MODEL: str = "gpt-6-luna"
    OPENAI_REASONING_EFFORT: ReasoningEffort = "none"
    OPENAI_TIMEOUT_SECONDS: int = Field(default=10, ge=1, le=60)
    OPENAI_MAX_OUTPUT_TOKENS: int = Field(default=600, ge=16, le=4000)
    LLM_PROVIDER: LlmProvider = "auto"
    LLM_STUB_SCENARIO: StubScenario = "ok"
    CHAT_ENABLED: bool = True
    CHAT_DAILY_LIMIT: int = Field(default=300, ge=1)
    CHAT_IP_LIMIT_PER_HOUR: int = Field(default=30, ge=1)
    CHAT_TURN_LIMIT: int = Field(default=10, ge=1, le=50)

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def demo_email_domains(self) -> frozenset[str]:
        """`DEMO_EMAIL_DOMAINS` を小文字化・前後空白除去して分けた集合。空なら制限なし。"""
        return frozenset(
            part.strip().lower() for part in self.DEMO_EMAIL_DOMAINS.split(",") if part.strip()
        )

    @property
    def is_test(self) -> bool:
        return self.APP_ENV == "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """設定をプロセス内で 1 回だけ読む。テストでは `get_settings.cache_clear()` で再読込。"""
    return Settings()
