from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "vendor/timeblock-assistant/SOURCE_LOCK.json"
SOURCE_SHA = "c12e37f8137552159d7756cf3d96eab0d812585f"

CANONICAL_ASSETS = {
    "static/css/mobile_input_keyboard_contract.css": ROOT
    / "app/static/css/mobile_input_keyboard_contract.css",
    "static/css/timeblock_v2_mobile_nav_safe_area_v1.css": ROOT
    / "app/static/css/timeblock_v2_mobile_nav_safe_area_v1.css",
    "static/js/assistant_pwa_standalone_viewport_v1.js": ROOT
    / "app/static/js/assistant_pwa_standalone_viewport_v1.js",
}


def _lock() -> dict[str, Any]:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _destinations(lock: dict[str, Any], source_path: str) -> list[str]:
    mapped = lock["destination_paths"][source_path]
    return [mapped] if isinstance(mapped, str) else mapped


def _campaign_changed_paths() -> set[str]:
    base = subprocess.run(
        ["git", "merge-base", "HEAD", "origin/main"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    output = subprocess.run(
        ["git", "diff", "--name-only", f"{base}..HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {path for path in output.splitlines() if path}


def test_timeblock_mobile_viewport_keyboard_contract_is_locked_and_scoped():
    lock = _lock()
    source_paths = set(lock["source_paths"])

    assert lock["source_repo"] == "Panjiaphu/fumap-bot-life"
    assert lock["source_sha"] == SOURCE_SHA
    assert lock["source_checkout_head"] == SOURCE_SHA
    assert lock["runtime_network_source"] is False
    assert len(lock["source_hashes"]) == len(lock["source_paths"])
    assert len(lock["destination_paths"]) == len(lock["source_paths"])

    for source_path, app_path in CANONICAL_ASSETS.items():
        destinations = _destinations(lock, source_path)
        vendor_relative = f"vendor/timeblock-assistant/{source_path}"
        app_relative = app_path.relative_to(ROOT).as_posix()

        assert source_path in source_paths
        assert vendor_relative in destinations
        assert app_relative in destinations
        assert _sha256(ROOT / vendor_relative) == lock["source_hashes"][source_path]
        assert _sha256(app_path) == lock["source_hashes"][source_path]

    initial_css = lock["runtime_asset_graph"]["assistant_initial_css"]
    assert initial_css.index("static/css/messaging_contact_v1.css") < initial_css.index(
        "static/css/mobile_input_keyboard_contract.css"
    )
    assert initial_css.index("static/css/mobile_input_keyboard_contract.css") < initial_css.index(
        "static/css/group_launcher_v3.css"
    ) < initial_css.index("static/css/timeblock_v2_mobile_nav_safe_area_v1.css")

    initial_js = lock["runtime_asset_graph"]["assistant_initial_js"]
    assert initial_js.index("static/js/live_translate_history.js") < initial_js.index(
        "static/js/assistant.js"
    ) < initial_js.index("static/js/assistant_pwa_standalone_viewport_v1.js") < initial_js.index(
        "static/js/assistant_mobile_conversation_v1.js"
    )

    ai_css = _text("app/static/css/assistant_mobile_conversation_v1.css")
    assert "--assistant-ai-viewport-bottom" in ai_css
    assert "height: var(--assistant-ai-viewport-bottom, 100dvh);" in ai_css

    direct_chat_css = _text("app/static/css/mobile_input_keyboard_contract.css")
    assert "--assistant-visual-viewport-height" in direct_chat_css
    assert "--assistant-visual-viewport-offset-top" in direct_chat_css
    assert "--timeblock-message-viewport-bottom" in direct_chat_css
    assert "transform: none;" in direct_chat_css

    assistant_js = _text("app/static/js/assistant.js")
    assert "--assistant-visual-viewport-bottom" in assistant_js
    assert "--assistant-visual-viewport-page-top" in assistant_js

    nav_css = _text("app/static/css/timeblock_v2_mobile_nav_safe_area_v1.css")
    assert "position: fixed;" in nav_css
    assert "inset: auto 0 0;" in nav_css
    assert "env(safe-area-inset-bottom" in nav_css
    assert "bottom: max(" not in nav_css

    standalone_js = _text("app/static/js/assistant_pwa_standalone_viewport_v1.js")
    for event_name in ("focusout", "orientationchange", "pageshow", "visibilitychange"):
        assert event_name in standalone_js
    assert "--assistant-visual-viewport-height" not in standalone_js

    runtime_adapter_css = _text("app/static/css/assistant_runtime_adapter.css")
    assert "assistant-ai-conversation-active .mobile-bottom-nav" in runtime_adapter_css
    assert "timeblock-mobile-immersive-conversation .mobile-bottom-nav" in runtime_adapter_css
    assert "display: none !important;" in runtime_adapter_css
    assert "padding-bottom: 0;" in runtime_adapter_css
    assert "--assistant-bottom-nav-height" in runtime_adapter_css
    assert "--assistant-ai-viewport-bottom" in runtime_adapter_css
    assert "--timeblock-message-viewport-bottom" in runtime_adapter_css
    assert "height: var(--assistant-ai-viewport-bottom, 100dvh);" in runtime_adapter_css
    assert "height: var(--timeblock-message-viewport-bottom, 100dvh);" in runtime_adapter_css

    assistant_template = _text("vendor/timeblock-assistant/templates/assistant/index.html")
    assert "filename='css/mobile_input_keyboard_contract.css'" in assistant_template
    assert "filename='css/timeblock_v2_mobile_nav_safe_area_v1.css'" in assistant_template
    assert "filename='js/assistant_pwa_standalone_viewport_v1.js'" in assistant_template

    campaign_paths = _campaign_changed_paths()
    # Group V3 is AI-COMMUNICATION-owned. Its template/runtime is intentionally
    # outside the Timeblock Direct 1:1 mobile keyboard campaign and may evolve
    # on the Group branch. Keep the canonical Direct/Assistant assets locked.
    direct_paths = {
        "app/templates/communication.html",
        "app/templates/assistant.html",
        "app/static/communication.js",
        "app/static/communication.css",
        "app/static/js/assistant.js",
        "app/static/js/assistant_pwa_standalone_viewport_v1.js",
        "app/static/css/mobile_input_keyboard_contract.css",
        "app/static/css/timeblock_v2_mobile_nav_safe_area_v1.css",
    }
    assert not any(
        path in direct_paths
        or path.startswith("app/static/js/assistant_")
        or path.startswith("app/static/css/assistant_")
        or path.startswith("vendor/timeblock-assistant/")
        for path in campaign_paths
    )
