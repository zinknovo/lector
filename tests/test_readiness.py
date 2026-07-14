import asyncio

from app.integrations.readiness import (
    CapabilitySkipped,
    CheckStatus,
    _check_apify,
    _validate_vector,
    run_readiness,
)


def test_readiness_reports_pass_fail_skip_and_redacts_secrets() -> None:
    async def passing() -> str:
        return "connected"

    async def failing() -> str:
        raise RuntimeError("request rejected for sk-live-secret")

    async def skipped() -> str:
        raise CapabilitySkipped("not configured")

    report = asyncio.run(
        run_readiness(
            {"pass", "fail", "skip"},
            checks={"pass": passing, "fail": failing, "skip": skipped},
            secrets=["sk-live-secret"],
        )
    )

    by_name = {check.name: check for check in report.checks}
    assert by_name["pass"].status == CheckStatus.PASS
    assert by_name["fail"].status == CheckStatus.FAIL
    assert "sk-live-secret" not in by_name["fail"].detail
    assert "***" in by_name["fail"].detail
    assert by_name["skip"].status == CheckStatus.SKIPPED
    assert report.exit_code == 1


def test_vector_validation_requires_1024_finite_numbers() -> None:
    assert _validate_vector([0.0] * 1024) == "1024-dimensional vector"

    for vector in ([0.0] * 10, [0.0] * 1023 + [float("nan")]):
        try:
            _validate_vector(vector)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid vector must be rejected")


def test_apify_check_uses_direct_amazon_source(monkeypatch) -> None:
    from app.integrations import readiness as module

    class Product:
        platform = "amazon"
        product_id = "B001"

    class FakeSource:
        token = None

        def __init__(self, api_token: str):
            self.token = api_token

        async def search(self, query: str, **filters):
            assert query == "wireless earbuds"
            assert filters["max_results"] == 1
            return [Product()]

    monkeypatch.setattr(module, "ApifyAmazonDataSource", FakeSource)

    detail = asyncio.run(_check_apify("real-token-value"))
    assert detail == "1 Amazon product (B001)"
