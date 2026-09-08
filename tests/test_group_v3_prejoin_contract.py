from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_group_v3_prejoin_is_explicit_and_device_coordinator_isolated():
    template = (ROOT / "app/templates/group_communication_v3.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app/static/group-v3/group_v3_app.js").read_text(encoding="utf-8")
    manager_js = (ROOT / "app/static/group-v3/group_device_manager.js").read_text(encoding="utf-8")
    runtime_css = (ROOT / "app/static/group-v3/group_v3_runtime.css").read_text(encoding="utf-8")

    assert "group_device_manager.js?v=20260904-prejoin-1" in template
    assert "prejoinOpen" in app_js
    assert 'action("prepare-prejoin"' in app_js
    assert 'action("confirm-prejoin"' in app_js
    assert "getUserMedia" not in app_js.split("async function connectWithGrant", 1)[0]
    assert "preserveStream" in app_js
    assert "permission_denied" in manager_js
    assert "device_not_found" in manager_js
    assert "device_busy" in manager_js
    assert "setSinkId" in manager_js
    assert "AudioContext" in manager_js
    assert ".prejoin-backdrop" in runtime_css
    assert "@media (max-width: 640px)" in runtime_css


def test_group_v3_prejoin_never_persists_handoff_or_media_secrets():
    manager_js = (ROOT / "app/static/group-v3/group_device_manager.js").read_text(encoding="utf-8")
    # Device ids/readiness are intentionally remembered locally so Call, Video,
    # and Radio can reuse one device setup.  Authentication and LiveKit material
    # must still never enter browser storage.
    assert 'var STORAGE_KEY = "group-v3-device-preferences-v1"' in manager_js
    assert 'JSON.stringify(Object.assign({}, preferences, { mediaReady: mediaReady }))' in manager_js
    assert "sessionStorage" not in manager_js
    for secret_name in ("handoff", "token", "livekit", "access_token", "refresh_token"):
        assert secret_name not in manager_js.lower()


def test_group_v3_media_reconnect_is_bounded_and_cleanup_cancels_stale_work():
    app_js = (ROOT / "app/static/group-v3/group_v3_app.js").read_text(encoding="utf-8")
    assert "mediaReconnectAttempts >= 3" in app_js
    assert "Math.pow(2, attempt)" in app_js
    assert "clearMediaReconnect" in app_js
    assert "keepReconnect" in app_js
    assert "devicechange" in app_js
    assert "beforeunload" in app_js or "pagehide" in app_js
    assert "group_media_stale_attempt" in app_js


def test_group_v3_incoming_ringtone_is_gesture_gated_and_single_tab_coordinated():
    template = (ROOT / "app/templates/group_communication_v3.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app/static/group-v3/group_v3_app.js").read_text(encoding="utf-8")
    ringtone_js = (ROOT / "app/static/group-v3/group_incoming_ringtone.js").read_text(encoding="utf-8")
    assert "group_incoming_ringtone.js?v=20260907-ringtone-2" in template
    assert "syncIncomingRingtone" in app_js
    assert "GroupV3IncomingRingtone.arm" in app_js
    assert "BroadcastChannel" in ringtone_js
    assert "navigator.locks.request" in ringtone_js
    assert '{ ifAvailable: true, mode: "exclusive" }' in ringtone_js
    assert "AudioContext" in ringtone_js
    assert "getUserMedia" not in ringtone_js
    assert "groupV3RingtonePreferences" in ringtone_js
    assert "durationSeconds" in ringtone_js
    assert "exhaustedKeys" in ringtone_js
    assert 'window.addEventListener("pagehide", stop)' in ringtone_js
    assert 'window.addEventListener("beforeunload", stop)' in ringtone_js
    assert 'document.addEventListener("visibilitychange"' in ringtone_js
    assert 'participant.invite_status === "invited"' in app_js
    assert 'state.mediaSession.status === "ringing"' in app_js
    assert 'state.mediaSession.initiated_by_membership_id === participant.membership_id' in app_js


def test_group_v3_ringtone_never_applies_to_radio_and_coordinates_with_tts():
    app_js = (ROOT / "app/static/group-v3/group_v3_app.js").read_text(encoding="utf-8")
    ringtone_js = (ROOT / "app/static/group-v3/group_incoming_ringtone.js").read_text(encoding="utf-8")
    tts_js = (ROOT / "app/static/group-v3/group_tts_manager.js").read_text(encoding="utf-8")

    ringtone_sync = app_js.split("function syncIncomingRingtone()", 1)[1].split(
        "function syncCallerRingback()", 1
    )[0]
    assert "radioSession" not in ringtone_sync
    assert "GroupV3IncomingRingtone.start(state.mediaSession.id)" in ringtone_sync
    assert 'CustomEvent("group-v3:ringtone-started"' in ringtone_js
    assert 'CustomEvent("group-v3:ringtone-stopped"' in ringtone_js
    assert 'window.addEventListener("group-v3:ringtone-started"' in tts_js
    assert 'window.addEventListener("group-v3:ringtone-stopped"' in tts_js
    assert "ringtoneActive = true" in tts_js
    assert "cancel();" in tts_js


def test_group_v3_caller_ringback_is_gesture_gated_and_stoppable():
    template = (ROOT / "app/templates/group_communication_v3.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app/static/group-v3/group_v3_app.js").read_text(encoding="utf-8")
    ringback_js = (ROOT / "app/static/group-v3/group_ringback.js").read_text(encoding="utf-8")
    assert "group_ringback.js?v=20260904-ringback-1" in template
    assert "GroupV3Ringback.start" in app_js
    assert "GroupV3Ringback.stop" in app_js
    assert "GroupV3Ringback.arm" in app_js
    assert "BroadcastChannel" in ringback_js
    assert "AudioContext" in ringback_js
    assert "pagehide" not in ringback_js or "stop" in ringback_js


def test_group_v3_attachment_viewer_has_authenticated_inline_media_and_mobile_exit():
    router = (ROOT / "app/group_v3/router.py").read_text(encoding="utf-8")
    service = (ROOT / "app/group_v3/service.py").read_text(encoding="utf-8")
    app_js = (ROOT / "app/static/group-v3/group_v3_app.js").read_text(encoding="utf-8")
    runtime_css = (ROOT / "app/static/group-v3/group_v3_runtime.css").read_text(encoding="utf-8")
    assert "/attachments/{attachment_id}/inline" in router
    assert '"Content-Disposition": f"inline;' in router
    assert "inline_media_not_supported" in router
    assert '"inline_url"' in service and '"is_image"' in service
    assert "attachmentViewer" in app_js
    assert 'data-action=\"close-attachment\"' in app_js
    assert ".attachment-viewer-backdrop" in runtime_css
    assert ".attachment-viewer-download" in runtime_css


def test_group_v3_media_roster_does_not_hide_mobile_participants():
    app_js = (ROOT / "app/static/group-v3/group_v3_app.js").read_text(encoding="utf-8")
    runtime_css = (ROOT / "app/static/group-v3/group_v3.css").read_text(encoding="utf-8")
    assert "media-participant-count" in app_js
    assert "count-" in app_js
    assert ".video-tile:nth-child(4)" not in runtime_css
    assert ".audio-participant-row > div:nth-child(n+4)" not in runtime_css
    assert "overflow-x: auto" in runtime_css
