from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_default_compose_uses_only_required_services() -> None:
    config = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))

    assert set(config["services"]) == {"mongodb", "agent", "gateway", "frontend"}
    assert set(config.get("volumes", {})) == {"mongodb-data"}
    assert set(config["services"]["agent"]["depends_on"]) == {"mongodb"}
    assert config["services"]["agent"]["ports"] == [
        "127.0.0.1:${AGENT_HOST_PORT:-8000}:8000"
    ]
