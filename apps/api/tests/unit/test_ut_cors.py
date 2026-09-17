"""CORS の単体確認（IT-CORS-01 の DB 不要版）。許可オリジン 1 つのみ・ワイルドカード禁止。"""

from __future__ import annotations

from tests.conftest import TEST_ORIGIN


async def test_ut_cors_other_origin_gets_no_allow_header(make_app, client_factory) -> None:
    client = client_factory(make_app())
    res = await client.options(
        "/api/v1/health",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in {k.lower() for k in res.headers}


async def test_ut_cors_allowed_origin_gets_header_with_credentials(
    make_app, client_factory
) -> None:
    client = client_factory(make_app())
    res = await client.options(
        "/api/v1/health",
        headers={"Origin": TEST_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == TEST_ORIGIN
    assert res.headers["access-control-allow-credentials"] == "true"


async def test_ut_cors_wildcard_or_empty_disables_cors(make_app, client_factory) -> None:
    for value in ("*", ""):
        client = client_factory(make_app(CORS_ALLOW_ORIGIN=value))
        res = await client.options(
            "/api/v1/health",
            headers={"Origin": "https://any.example.com", "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" not in {k.lower() for k in res.headers}, value
