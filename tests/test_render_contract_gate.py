from __future__ import annotations

from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.integrations.timeblock.client import TimeblockIntegrationError
from app.main import create_app
from scripts.check_env import main as check_env
from scripts.verify_assistant_source_lock import main as verify_source_lock


RENDER_BLUEPRINT = Path(__file__).resolve().parents[1] / "render.yaml"
BROWSER_WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "communication-browser-qa.yml"
)


def _production_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("SECRET_KEY", "production-secret-key-with-at-least-32-bytes")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://guilua.onrender.com")
    monkeypatch.setenv("TIMEBLOCK_APP_URL", "https://timeblock.example")
    monkeypatch.setenv("ALLOW_DEVELOPMENT_SESSION_FALLBACK", "false")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)


def _complete_group_v3_env(monkeypatch) -> None:
    monkeypatch.setenv("GROUP_V3_ENABLED", "true")
    monkeypatch.setenv("GROUP_HANDOFF_AUDIENCE", "ai-communication-group-v3")
    monkeypatch.setenv("DATABASE_URL", "postgresql://group-db.internal/group_v3")
    monkeypatch.setenv("GROUP_MESSAGE_ENCRYPTION_KEY", "ab" * 32)
    monkeypatch.setenv("GROUP_MEDIA_ENABLED", "true")
    monkeypatch.setenv("GROUP_LIVEKIT_URL", "wss://group-v3.livekit.cloud")
    monkeypatch.setenv("GROUP_LIVEKIT_API_KEY", "livekit-api-key")
    monkeypatch.setenv("GROUP_LIVEKIT_API_SECRET", "livekit-api-secret")
    monkeypatch.setenv("GROUP_LIVEKIT_REGION", "Singapore")
    monkeypatch.setenv("GROUP_LIVEKIT_TOKEN_TTL_SECONDS", "300")
    monkeypatch.setenv("GROUP_RADIO_V3_ENABLED", "true")
    monkeypatch.setenv("GROUP_RADIO_REDIS_URL", "redis://group-radio.internal:6379")
    monkeypatch.setenv("GROUP_RADIO_FLOOR_LEASE_SECONDS", "15")
    monkeypatch.setenv("GROUP_RADIO_HEARTBEAT_SECONDS", "5")
    monkeypatch.setenv("GROUP_TRANSLATION_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "existing-openai-key")


def test_production_environment_fails_closed_without_timeblock_contract_credentials(
    monkeypatch, capsys
):
    _production_env(monkeypatch)
    monkeypatch.delenv("TIMEBLOCK_API_URL", raising=False)
    monkeypatch.delenv("TIMEBLOCK_API_KEY", raising=False)

    assert check_env(["--phase", "runtime"]) == 1
    errors = capsys.readouterr().err
    assert "TIMEBLOCK_API_URL is required" in errors
    assert "TIMEBLOCK_API_KEY must contain at least 32 bytes" in errors


def test_production_environment_accepts_complete_contract_configuration(monkeypatch):
    _production_env(monkeypatch)
    monkeypatch.setenv("TIMEBLOCK_API_URL", "https://timeblock.example")
    monkeypatch.setenv("TIMEBLOCK_API_KEY", "server-contract-key-with-at-least-32-bytes")

    assert check_env(["--phase", "build"]) == 0


def test_production_group_v3_fails_closed_without_provider_infrastructure(
    monkeypatch, capsys
):
    _production_env(monkeypatch)
    monkeypatch.setenv("TIMEBLOCK_API_URL", "https://timeblock.example")
    monkeypatch.setenv("TIMEBLOCK_API_KEY", "server-contract-key-with-at-least-32-bytes")
    monkeypatch.setenv("GROUP_V3_ENABLED", "true")
    monkeypatch.setenv("GROUP_MEDIA_ENABLED", "true")
    monkeypatch.setenv("GROUP_RADIO_V3_ENABLED", "true")
    monkeypatch.setenv("GROUP_TRANSLATION_ENABLED", "true")

    assert check_env(["--phase", "runtime"]) == 1
    errors = capsys.readouterr().err
    assert "DATABASE_URL must use PostgreSQL" in errors
    assert "GROUP_MESSAGE_ENCRYPTION_KEY must decode to exactly 32 bytes" in errors
    assert "GROUP_LIVEKIT_URL must be a credential-free WSS URL" in errors
    assert "GROUP_RADIO_REDIS_URL must be a valid Redis/Valkey URL" in errors
    assert "OPENAI_API_KEY is required" in errors


def test_production_group_v3_accepts_complete_release_configuration(monkeypatch):
    _production_env(monkeypatch)
    monkeypatch.setenv("TIMEBLOCK_API_URL", "https://timeblock.example")
    monkeypatch.setenv("TIMEBLOCK_API_KEY", "server-contract-key-with-at-least-32-bytes")
    _complete_group_v3_env(monkeypatch)

    assert check_env(["--phase", "runtime"]) == 0


def test_production_environment_requires_exact_deploy_identity(monkeypatch, capsys):
    _production_env(monkeypatch)
    monkeypatch.setenv("TIMEBLOCK_API_URL", "https://timeblock.example")
    monkeypatch.setenv("TIMEBLOCK_API_KEY", "server-contract-key-with-at-least-32-bytes")
    monkeypatch.delenv("DEPLOYMENT_VERSION", raising=False)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)

    assert check_env(["--phase", "build"]) == 1
    assert "exact 40-64 character hexadecimal deploy SHA" in capsys.readouterr().err


def test_settings_use_render_git_commit_as_deployment_version(monkeypatch):
    render_sha = "b" * 40
    monkeypatch.delenv("DEPLOYMENT_VERSION", raising=False)
    monkeypatch.setenv("RENDER_GIT_COMMIT", render_sha)

    settings = Settings(_env_file=None)

    assert settings.deployment_version == render_sha


def test_settings_prefer_render_git_commit_over_stale_manual_version(monkeypatch):
    render_sha = "d" * 40
    monkeypatch.setenv("DEPLOYMENT_VERSION", "c" * 40)
    monkeypatch.setenv("RENDER_GIT_COMMIT", render_sha)

    settings = Settings(
        _env_file=None,
        app_env="test",
        debug=True,
        secret_key="render-identity-test-key",
        public_base_url="http://testserver",
        timeblock_app_url="http://timeblock.test",
    )

    assert settings.deployment_version == render_sha


def test_build_gate_verifies_every_source_locked_destination():
    assert verify_source_lock() == 0


def test_render_blueprint_targets_existing_fail_closed_service():
    blueprint = RENDER_BLUEPRINT.read_text(encoding="utf-8")

    assert "name: AI-COMMUNICATION-Timeblock" in blueprint
    assert "branch: main" in blueprint
    assert "autoDeployTrigger: off" in blueprint
    assert "plan: starter" in blueprint
    assert "healthCheckPath: /readyz/" in blueprint
    assert "preDeployCommand: bash scripts/predeploy_render.sh" in blueprint
    assert not re.search(r"^\s+value:\s+(?:true|false)\s*$", blueprint, re.MULTILINE)
    assert re.search(r"key: SECRET_KEY\s+sync: false", blueprint)
    assert re.search(r"key: TIMEBLOCK_API_KEY\s+sync: false", blueprint)
    for key in (
        "GROUP_V3_ENABLED",
        "GROUP_MEDIA_ENABLED",
        "GROUP_RADIO_V3_ENABLED",
        "GROUP_TRANSLATION_ENABLED",
    ):
        assert re.search(rf"key: {key}\s+value: \"true\"", blueprint)


def test_browser_workflow_does_not_leak_development_fallback_into_production_tests():
    workflow = BROWSER_WORKFLOW.read_text(encoding="utf-8")

    assert re.search(
        r'name: Run default test suite\s+env:\s+BROWSER_QA_ENABLED: "0"\s+'
        r'ALLOW_DEVELOPMENT_SESSION_FALLBACK: "false"',
        workflow,
    )


def _readiness_settings() -> Settings:
    return Settings(
        app_env="test",
        debug=True,
        secret_key="readiness-test-key",
        public_base_url="http://testserver",
        timeblock_app_url="https://timeblock.example",
        timeblock_api_url="https://timeblock.example",
        timeblock_api_key="server-contract-key-with-at-least-32-bytes",
        allowed_websocket_origins="http://testserver",
        allowed_timeblock_handoff_origins="https://timeblock.example",
        deployment_version="c" * 40,
    )


def test_readiness_requires_timeblock_client_contract_v2():
    app = create_app(_readiness_settings())
    app.state.timeblock_client = SimpleNamespace(
        contract_capabilities=AsyncMock(
            return_value={
                "contract_version": "2",
                "authority": "timeblock",
                "capabilities": ["identity.read"],
            }
        )
    )
    with TestClient(app) as client:
        ready = client.get("/readyz/")

    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["contract_version"] == "2"
    assert ready.json()["deployment_version"] == "c" * 40


def test_readiness_is_503_when_timeblock_contract_is_unavailable():
    app = create_app(_readiness_settings())
    app.state.timeblock_client = SimpleNamespace(
        contract_capabilities=AsyncMock(
            side_effect=TimeblockIntegrationError("timeblock_contract_unavailable")
        )
    )
    with TestClient(app) as client:
        unavailable = client.get("/readyz/")

    assert unavailable.status_code == 503
    assert unavailable.json()["dependency"] == "timeblock_client_contract_v2"


def _group_v3_readiness_app(tmp_path, revision: str | None):
    settings = Settings(
        app_env="test",
        debug=True,
        secret_key="group-v3-readiness-test-key",
        public_base_url="http://testserver",
        timeblock_app_url="https://timeblock.example",
        timeblock_api_url="https://timeblock.example",
        timeblock_api_key="server-contract-key-with-at-least-32-bytes",
        allowed_websocket_origins="http://testserver",
        allowed_timeblock_handoff_origins="https://timeblock.example",
        deployment_version="e" * 40,
        group_v3_enabled=True,
        group_message_encryption_key="ab" * 32,
        database_url=f"sqlite:///{(tmp_path / 'ready.sqlite3').as_posix()}",
    )
    app = create_app(settings)
    if revision is not None:
        with app.state.database.engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": revision},
            )
    app.state.timeblock_client = SimpleNamespace(
        contract_capabilities=AsyncMock(
            return_value={
                "contract_version": "2",
                "authority": "timeblock",
                "capabilities": ["identity.read"],
            }
        )
    )
    return app


def test_group_v3_readiness_reports_native_contract_and_schema(tmp_path):
    app = _group_v3_readiness_app(tmp_path, "20260904_0023")
    with TestClient(app) as client:
        ready = client.get("/readyz/")

    assert ready.status_code == 200
    assert ready.json()["authority"] == "ai-communication"
    assert ready.json()["contract_version"] == "3"
    assert ready.json()["identity_authority"] == "timeblock"
    assert ready.json()["identity_contract_version"] == "2"
    assert ready.json()["schema_revision"] == "20260904_0023"
    assert ready.json()["capabilities"]["group_chat"] is True


def test_group_v3_readiness_is_503_when_schema_is_not_at_head(tmp_path):
    app = _group_v3_readiness_app(tmp_path, "20260831_0015")
    with TestClient(app) as client:
        unavailable = client.get("/readyz/")

    assert unavailable.status_code == 503
    assert unavailable.json()["dependency"] == "group_v3_schema"
    assert unavailable.json()["expected_revision"] == "20260904_0023"
