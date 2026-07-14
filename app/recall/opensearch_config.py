"""Shared OpenSearch connection settings for local scripts and services."""

import os
from collections.abc import Mapping
from typing import Any


def opensearch_connection_settings(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    values = environ or os.environ
    host = values.get("OPENSEARCH_HOST", "localhost")
    settings: dict[str, Any] = {
        "hosts": [
            {
                "host": host,
                "port": int(values.get("OPENSEARCH_PORT", "9200")),
            }
        ],
        "use_ssl": values.get("OPENSEARCH_USE_SSL", "false").lower() == "true",
    }
    user = values.get("OPENSEARCH_USER")
    password = values.get("OPENSEARCH_PASS")
    if user and password:
        settings["http_auth"] = (user, password)
    return settings
