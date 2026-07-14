from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_compose_publishes_local_services_on_loopback_only() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))

    for name, service in compose["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name}: {port}"


def test_frontend_proxy_authenticates_before_injecting_gateway_key() -> None:
    config = (ROOT / "frontend/nginx.conf.template").read_text(encoding="utf-8")

    assert 'auth_basic "Lector";' in config
    assert "auth_basic_user_file /etc/nginx/.htpasswd;" in config
    assert "proxy_set_header X-API-Key ${LECTOR_API_KEY};" in config
