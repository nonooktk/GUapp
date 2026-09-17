"""アプリ設定（pydantic-settings）。

値はすべて環境変数から読む（設計仕様書 8.2、`.env.example` のキー名と一致）。
秘匿値をコードに書かない（規定 §3）。
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]


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

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_test(self) -> bool:
        return self.APP_ENV == "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """設定をプロセス内で 1 回だけ読む。テストでは `get_settings.cache_clear()` で再読込。"""
    return Settings()
