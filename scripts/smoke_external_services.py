"""Run strict external-capability checks and emit one JSON report."""

import argparse
import asyncio
import os

from dotenv import load_dotenv

from app.integrations.readiness import run_readiness

ALL_SERVICES = {"apify", "mongodb", "llm", "web_search", "opensearch", "tower"}


def _parse_services(raw: str) -> set[str]:
    if raw == "all" or raw == "configured":
        return set(ALL_SERVICES)
    return {item.strip() for item in raw.split(",") if item.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Lector external integrations")
    parser.add_argument("--services", default="configured")
    args = parser.parse_args()
    load_dotenv()
    secrets = [
        os.environ.get("APIFY_API_TOKEN", ""),
        os.environ.get("LLM_API_KEY", ""),
        os.environ.get("MONGODB_URL", ""),
        os.environ.get("OPENSEARCH_PASS", ""),
    ]
    report = asyncio.run(
        run_readiness(_parse_services(args.services), secrets=secrets)
    )
    print(report.model_dump_json(indent=2))
    raise SystemExit(report.exit_code)


if __name__ == "__main__":
    main()
