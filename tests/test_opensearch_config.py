from app.recall.opensearch_config import opensearch_connection_settings


def test_local_opensearch_settings_do_not_require_credentials() -> None:
    settings = opensearch_connection_settings(
        {"OPENSEARCH_HOST": "localhost", "OPENSEARCH_PORT": "19200"}
    )

    assert settings["hosts"] == [{"host": "localhost", "port": 19200}]
    assert "http_auth" not in settings
    assert settings["use_ssl"] is False


def test_remote_opensearch_settings_include_credentials_and_tls() -> None:
    settings = opensearch_connection_settings(
        {
            "OPENSEARCH_HOST": "search.internal",
            "OPENSEARCH_USER": "lector",
            "OPENSEARCH_PASS": "secret",
            "OPENSEARCH_USE_SSL": "true",
        }
    )

    assert settings["http_auth"] == ("lector", "secret")
    assert settings["use_ssl"] is True
