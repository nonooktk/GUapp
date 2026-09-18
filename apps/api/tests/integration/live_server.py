"""起動済み uvicorn へ HTTP で送るためのフィクスチャ（テスト設計書 1.4 #1）。

- 空きポートを動的に取り、`python -m uvicorn app.main:app` を `subprocess.Popen` で起動する
  （ポート 8000 は開発サーバーが使うので使わない）
- 環境: `APP_ENV=test`・`DATABASE_URL`=guapp_test・`INTERNAL_TOKEN`・`TEST_RESERVE_DELAY_MS=30`
  （1.4 #7。競合の窓を広げる。Wave 3 で 10 → 30 ms）。DB プールは app.core.db の既定（20＋10）
- `/api/v1/health` が 200 を返すまで待ち、続けて `GET /api/v1/products` を 1 回投げてウォームアップ
  （DB プールの初回接続・ORM の初期化を、同時実行テストの計測前に済ませる）
- 終了時はプロセスツリーごと止める（Windows: `taskkill /T /F /PID`）
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from tests.conftest import TEST_INTERNAL_TOKEN, TEST_ORIGIN

API_DIR = Path(__file__).resolve().parents[2]
HEALTH_TIMEOUT_SECONDS = 40.0
# 1.4 #7 の「引当の読み書き間の待ち」。同時性を作りやすくするため 10 → 30。
# 環境変数 GUAPP_IT_RESERVE_DELAY_MS で上書きできる（再試行経路の確認用。通常は未設定）
RESERVE_DELAY_MS = int(os.environ.get("GUAPP_IT_RESERVE_DELAY_MS", "30"))


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass(frozen=True)
class LiveServer:
    base_url: str
    port: int
    pid: int
    log_path: Path


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def _wait_health(base_url: str, proc: subprocess.Popen, log_path: Path) -> None:
    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    last_error = ""
    with httpx.Client(timeout=2.0) as client:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(
                    f"live_server が起動前に終了しました（exit={proc.returncode}）。"
                    f" ログ: {log_path}"
                )
            try:
                res = client.get(f"{base_url}/api/v1/health")
                if res.status_code == 200:
                    return
                last_error = f"health {res.status_code}"
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
            time.sleep(0.2)
    raise RuntimeError(f"live_server の health が通りません（{last_error}）。ログ: {log_path}")


def _warm_up(base_url: str) -> None:
    """ダミー要求 1 回で DB プールの初回接続・ORM の初期化を済ませる（読み取りのみ）。"""
    headers = {"X-Internal-Token": TEST_INTERNAL_TOKEN}
    with httpx.Client(timeout=10.0) as client:
        res = client.get(f"{base_url}/api/v1/products", headers=headers)
        if res.status_code != 200:
            raise RuntimeError(
                f"live_server のウォームアップに失敗（products {res.status_code}）: {res.text}"
            )


@pytest.fixture(scope="session")
def live_server(
    test_database_url: str, migrated_schema: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[LiveServer]:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": test_database_url,
            "INTERNAL_TOKEN": TEST_INTERNAL_TOKEN,
            "CORS_ALLOW_ORIGIN": TEST_ORIGIN,
            "TEST_RESERVE_DELAY_MS": str(RESERVE_DELAY_MS),
            "PYTHONUTF8": "1",
        }
    )
    env.pop("PAYMENT_STUB_RESULT", None)  # 既定（ok）で起動する

    log_path = tmp_path_factory.mktemp("live_server") / "uvicorn.log"
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=API_DIR,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_health(base_url, proc, log_path)
            _warm_up(base_url)
            yield LiveServer(base_url=base_url, port=port, pid=proc.pid, log_path=log_path)
        finally:
            _kill_tree(proc)
