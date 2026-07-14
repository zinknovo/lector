import asyncio

from app.integrations.readiness import (
    CapabilitySkipped,
    CheckStatus,
    _check_apify,
    _check_mongodb,
    _check_web_search,
    _production_checks,
    run_readiness,
)
from app.tools.web_search import SearchResult, WebSearchOutput


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


def test_production_checks_exclude_removed_services() -> None:
    assert set(_production_checks()) == {"apify", "mongodb", "llm", "web_search"}


def test_readiness_times_out_each_external_check() -> None:
    async def hanging() -> str:
        await asyncio.sleep(1)
        return "late"

    report = asyncio.run(
        run_readiness(
            {"hanging"},
            checks={"hanging": hanging},
            timeout_seconds=0.01,
        )
    )

    assert report.checks[0].status == CheckStatus.FAIL
    assert "TimeoutError" in report.checks[0].detail


def test_apify_check_uses_direct_amazon_source(monkeypatch) -> None:
    from app.integrations import readiness as module

    class Product:
        platform = "amazon"
        product_id = "B001"

    class FakeSource:
        token = None
        timeout = None

        def __init__(
            self,
            api_token: str,
            request_timeout_seconds: float,
            max_retries: int,
            use_cache: bool,
        ):
            self.token = api_token
            type(self).timeout = request_timeout_seconds
            assert max_retries == 1
            assert use_cache is False

        async def search(self, query: str, **filters):
            assert query == "wireless earbuds"
            assert filters["max_results"] == 1
            return [Product()]

    monkeypatch.setattr(module, "ApifyAmazonDataSource", FakeSource)
    monkeypatch.setenv("READINESS_TIMEOUT_SECONDS", "10")

    detail = asyncio.run(_check_apify("real-token-value"))
    assert detail == "1 Amazon product (B001)"
    assert FakeSource.timeout == 8


def test_mongodb_check_pings_and_round_trips_cache(monkeypatch) -> None:
    documents = {}

    class Collection:
        def replace_one(self, query, document, upsert):
            assert upsert is True
            documents[query["_id"]] = document

        def find_one(self, query):
            return documents.get(query["_id"])

        def delete_one(self, query):
            documents.pop(query["_id"], None)

    collection = Collection()

    class Database:
        def __getitem__(self, name):
            assert name == "product_search_cache"
            return collection

    class Admin:
        def command(self, name):
            assert name == "ping"

    class Client:
        admin = Admin()
        closed = False

        def __init__(
            self,
            url,
            serverSelectionTimeoutMS,
            connectTimeoutMS,
            socketTimeoutMS,
        ):
            assert url == "mongodb://readiness-host/lector"
            assert serverSelectionTimeoutMS == 3000
            assert connectTimeoutMS == 3000
            assert socketTimeoutMS == 3000

        def __getitem__(self, name):
            assert name == "lector"
            return Database()

        def close(self):
            type(self).closed = True

    monkeypatch.setenv("MONGODB_URL", "mongodb://readiness-host/lector")
    monkeypatch.setattr("pymongo.MongoClient", Client)

    assert asyncio.run(_check_mongodb()) == "ping and cache round-trip"
    assert Client.closed is True


def test_web_search_readiness_accepts_deepseek_auto_backend(monkeypatch) -> None:
    from app.tools.web_search import web_search as tool

    async def fake_ainvoke(_self, _args):
        return WebSearchOutput(
            query="Amazon ecommerce trend today",
            provider="deepseek_anthropic",
            status="ok",
            results=[
                SearchResult(
                    title="Market report",
                    url="https://example.com/report",
                    content="Evidence",
                )
            ],
        )

    monkeypatch.setenv("LLM_WEB_SEARCH_BACKEND", "auto")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setattr(type(tool), "ainvoke", fake_ainvoke)

    assert asyncio.run(_check_web_search()) == "1 cited result"
