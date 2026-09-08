"""Actual Group template/scripts, deterministic API + media boundaries.

These checks are browser integration, not physical-device/LiveKit cloud proof.
Run once after source freeze: BROWSER_QA_ENABLED=1 pytest this-file.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlencode, urlparse

import pytest
from jinja2 import Environment

if os.getenv("BROWSER_QA_ENABLED") != "1":
    pytest.skip("Explicit final browser QA gate", allow_module_level=True)
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "app/static/group-v3"

DEVICE = """
window.__mediaCounts={acquire:0,publish:0,rooms:0,attach:0,audioAttach:0,audioPlay:0,connect:0,disconnect:0,startAudio:0};
window.__devicePrefs=JSON.parse(localStorage.getItem('qa-device-prefs')||'{}');
window.__spoken=[];
speechSynthesis.cancel=()=>{};speechSynthesis.resume=()=>{};
speechSynthesis.getVoices=()=>[{name:'QA voice',lang:'vi-VN'}];
speechSynthesis.speak=utterance=>queueMicrotask(()=>{
  if(utterance.text!=='\u200b')window.__spoken.push(utterance.text);
  utterance.onstart?.();utterance.onend?.();
});
window.__makeStream=()=> {
  const canvas=document.createElement('canvas');canvas.width=640;canvas.height=360;
  const c=canvas.getContext('2d');c.fillStyle='#186f62';c.fillRect(0,0,640,360);
  c.fillStyle='white';c.font='40px sans-serif';c.fillText('QA video source',80,180);
  const stream=canvas.captureStream(10);
  const paint=setInterval(()=>{c.fillStyle='#186f62';c.fillRect(0,0,640,360);c.fillStyle='white';c.fillText('QA video source',80,180);},100);
  stream.getVideoTracks()[0].addEventListener('ended',()=>clearInterval(paint));
  const audio=new AudioContext(), oscillator=audio.createOscillator(), dest=audio.createMediaStreamDestination();
  oscillator.connect(dest);oscillator.start();stream.addTrack(dest.stream.getAudioTracks()[0]);
  return stream;
};
window.GroupV3DeviceManager={
 enumerate:async()=>({audioInputs:[{deviceId:'mic-qa',label:'QA microphone'}],videoInputs:[{deviceId:'camera-qa',label:'QA camera'}],audioOutputs:[{deviceId:'speaker-qa',label:'QA speaker'}]}),
 remembered:k=>__devicePrefs[k]||'',remember:(k,v)=>{if(v)__devicePrefs[k]=v;else delete __devicePrefs[k];localStorage.setItem('qa-device-prefs',JSON.stringify(__devicePrefs));},
 acquire:async(options)=>{__mediaCounts.acquire++;window.__lastAcquire=options;const stream=__makeStream();if(options?.mediaKind==='audio')stream.getVideoTracks().forEach(t=>{t.stop();stream.removeTrack(t);});return window.__local=stream;},
 startMeter:()=>()=>{},stop:()=>{if(window.__local)__local.getTracks().forEach(t=>t.stop());},
 setOutput:async(e,v)=>{GroupV3DeviceManager.remember('audioOutput',v);return true;},applyOutput:async()=>({supported:true,applied:true,mode:'selected'}),
 outputSelectionSupported:()=>true,preferences:()=>({...__devicePrefs}),normalizeError:e=>({code:e.code||'device_error'}),onDeviceChange:()=>()=>{}
};
window.__eventSources=[];
window.EventSource=class {
 constructor(){this.listeners={};__eventSources.push(this);}
 addEventListener(k,f){(this.listeners[k]||(this.listeners[k]=[])).push(f);}
 emit(k,data={}){(this.listeners[k]||[]).forEach(f=>f({data:JSON.stringify(data)}));}
 close(){}
};
window.LivekitClient={
 RoomEvent:{TrackSubscribed:'sub',TrackUnsubscribed:'unsub',Disconnected:'disconnected',ActiveSpeakersChanged:'speakers',AudioPlaybackStatusChanged:'audio-playback'},
 Track:{Source:{Camera:'camera',Microphone:'microphone'}},
 Room:class {
  constructor(){__mediaCounts.rooms++;this.events={};this.remoteParticipants=new Map();
    this.canPlaybackAudio=!window.__qaBlockedAudio;
    this.localParticipant={publishTrack:async()=>{__mediaCounts.publish++;}};}
  on(k,f){this.events[k]=f;return this;}
  async connect(){__mediaCounts.connect++;
   if(window.__qaDeferConnect)await new Promise(resolve=>{window.__qaReleaseConnect=resolve;});
   const stream=__makeStream(),publications=new Map();
   if(window.__qaMediaKind==='video'){
    const videoTrack={kind:'video',sid:'remote-video-1',mediaStreamTrack:stream.getVideoTracks()[0],
     attach(){__mediaCounts.attach++;const node=document.createElement('video');node.srcObject=stream;node.muted=true;this.el=node;return node;},
     detach(){return this.el?[this.el]:[];}};
    publications.set('v',{track:videoTrack});this.events.sub?.(videoTrack,{}, {identity:'guest'});
   }
   const audioTrack={kind:'audio',sid:'remote-audio-1',mediaStreamTrack:stream.getAudioTracks()[0],
    attach(){__mediaCounts.audioAttach++;const node=document.createElement('audio');
     if(!window.__qaBlockedAudio)node.srcObject=stream;
     node.play=async()=>{__mediaCounts.audioPlay++;if(window.__qaBlockedAudio&&!window.__qaAudioUnlocked)throw new DOMException('blocked','NotAllowedError');node.dispatchEvent(new Event('playing'));};
     this.el=node;return node;},detach(){return this.el?[this.el]:[];}};
   publications.set('a',{track:audioTrack});this.remoteParticipants.set('guest',{identity:'guest',trackPublications:publications});
   this.events.sub?.(audioTrack,{}, {identity:'guest'});
  }
  async startAudio(){__mediaCounts.startAudio++;window.__qaAudioUnlocked=true;this.canPlaybackAudio=true;this.events['audio-playback']?.();}
  removeAllListeners(){this.events={};}
  disconnect(){__mediaCounts.disconnect++;window.__qaLifecycle?.('disconnect');}
 }
};
"""


@pytest.fixture
def page(chromium_browser):
    context = chromium_browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    page = context.new_page()
    page.set_default_timeout(7000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page
    assert not errors, errors
    context.close()


@pytest.mark.parametrize("width,height", [(1440,900),(390,844),(844,390)])
@pytest.mark.parametrize("count", [2,3,4])
def test_r1_video_layout_presets_reset_and_touch_contract(page, tmp_path, width, height, count):
    page.set_viewport_size({"width":width,"height":height})
    boot(page, participant_count=count)
    assert page.url.endswith("/group/video")
    expect(page.locator(".video-stage")).to_be_visible()
    before = page.evaluate("({...__mediaCounts})")
    for mode in ["GRID","SPEAKER","CUSTOM","AUTO"]:
        page.locator("[data-video-layout]").select_option(mode)
        expect(page.locator(".video-grid")).to_have_attribute("data-layout",mode)
        tiles = page.locator(".video-tile:visible")
        assert tiles.count() == count
        boxes = [tiles.nth(i).bounding_box() for i in range(count)]
        # Filmstrip may page horizontally; it must never be an unusable sliver.
        assert all(b["width"] >= 140 and b["height"] >= 60 for b in boxes), (mode,boxes)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        if width < 1000:
            assert page.locator(".native-main").bounding_box()["width"] == width
            assert page.locator(".video-panel-toolbar").bounding_box()["height"] <= 52
            assert page.locator(".video-grid").bounding_box()["height"] >= page.locator(".video-stage").bounding_box()["height"] * .4
        if mode == "CUSTOM":
            page.locator("[data-video-drag]").first.press("ArrowRight")
            assert page.evaluate("GroupV3VideoLayout.snapshot().customOrder.length") == count
    page.locator("[data-video-reset]").click()
    assert page.evaluate("GroupV3VideoLayout.snapshot().customOrder") == []
    assert page.evaluate("({...__mediaCounts})") == before
    page.screenshot(path=str(tmp_path/f"r1-video-{width}-{count}.png"), animations="disabled")

@pytest.mark.parametrize("locale,label", [("vi","Phát hiện ngôn ngữ"),("en","Detect language"),("zh-TW","自動偵測語言")])
def test_r1_auto_detect_text_keeps_profile_canonical(page, locale, label):
    boot(page, locale=locale)
    page.locator("[data-workspace-action=translation-plus]").click()
    expect(page.locator("[data-v2-source] option[value=auto]")).to_have_text(label)
    page.locator("[data-v2-source]").select_option("auto")
    requests=[]
    page.on("request",lambda r:requests.append(r) if r.method == "PUT" and r.url.endswith("/translation/profile") else None)
    def submit(route):
        assert route.request.post_data_json["source_language"] == "auto"
        route.fulfill(content_type="application/json",body=json.dumps({"segment":{
            "id":"auto-text","source_language":"en","source_text":"Hello team","state":"FINAL","author_view":True,"variants":[]}}))
    page.route("**/translation/segments/text",submit)
    page.locator("[data-v2-text]").fill("Hello team")
    page.locator("[data-v2-action=send]").click()
    expect(page.locator("[data-segment-id=auto-text]")).to_be_visible()
    assert requests and all(r.post_data_json["spoken_language"] != "auto" for r in requests)
    assert "auto" not in page.locator("[data-segment-id=auto-text]").inner_text()

def test_r1_auto_voice_busy_recoverable_error_and_retry(page):
    button=voice_setup(page)
    page.locator("[data-v2-source]").select_option("auto")
    uploads=[]
    def failed(route):
        uploads.append(route.request.post_data_buffer)
        route.fulfill(status=422,content_type="application/json",
            body='{"detail":"group_translation_detected_language_unsupported"}')
    page.route("**/translation/segments/voice",failed)
    button.click()
    expect(button).to_have_attribute("data-voice-icon","save")
    # Observe the busy icon before the mocked response resolves.
    page.evaluate("""() => {window.__voiceIcons=[];new MutationObserver(()=>{
      __voiceIcons.push(document.querySelector('[data-v2-action=record]').dataset.voiceIcon);
    }).observe(document.querySelector('[data-v2-action=record]'),{attributes:true,attributeFilter:['data-voice-icon']});}""")
    button.click()
    expect(page.locator("[data-v2-error]")).to_contain_text("chọn ngôn ngữ")
    expect(button).to_have_attribute("data-voice-icon","mic")
    assert len(uploads)==1 and b"\r\n\r\nauto\r\n" in uploads[0]
    assert "languages" in page.evaluate("__voiceIcons")
    button.click()
    expect(button).to_have_attribute("data-voice-icon","save")

def test_r1_video_history_visible_after_ended_runtime(page):
    boot(page)
    item={"id":"ended-video-text","runtime_kind":"video","source_language":"vi","source_text":"Durable source",
        "state":"FINAL","author_view":True,"speaker_display_name":"Nguyễn Minh","created_at":"2026-09-05T07:00:00Z","variants":[]}
    page.route("**/translation/v2-history?*",lambda r:r.fulfill(content_type="application/json",body=json.dumps({"segments":[item]})))
    page.locator(".call-control-dock [data-action=leave-media]").click()
    page.wait_for_function("!GroupV3Runtime.snapshot().media_connected")
    page.evaluate("document.querySelector('[data-surface=\"chat-translation\"]').click()")
    expect(page.locator("[data-segment-id=ended-video-text]")).to_be_visible()
    expect(page.locator("[data-segment-id=ended-video-text]")).to_contain_text("Durable source")
    expect(page.locator("[data-segment-id=ended-video-text] time")).to_have_attribute("datetime","2026-09-05T07:00:00Z")

@pytest.mark.parametrize("width,height", [(1440,900),(390,844),(844,390)])
def test_r1_radio_tap_stop_text_history_leave_reopen(page,tmp_path,width,height):
    page.set_viewport_size({"width":width,"height":height})
    boot(page,surface="radio",connected=False)
    page.locator(".radio-ptt").click()
    page.wait_for_function("GroupV3Runtime.snapshot().media_connected")
    page.evaluate("()=>{window.__testMime='audio/mp4';"+RECORDER+"}")
    page.locator(".radio-ptt").click()
    expect(page.locator(".radio-ptt")).to_have_attribute("data-action","stop-radio")
    assert page.evaluate("__recorders") == 1 and page.evaluate("__mediaCounts.acquire") == 1
    page.locator(".radio-ptt").click()
    expect(page.locator("[data-segment-id=radio-segment]")).to_be_visible()
    expect(page.locator(".radio-ptt")).to_have_attribute("data-action","start-radio")
    expect(page.locator(".radio-ptt")).to_have_count(1)
    dock=page.locator(".radio-room-dock").bounding_box()
    assert dock["y"]+dock["height"] <= height
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(tmp_path/f"r1-radio-{width}.png"),animations="disabled")
    page.locator(".radio-room-dock [data-action=leave-radio]").click()
    page.wait_for_url("**/group/chat")
    page.locator("[data-surface=radio]:visible").click()
    expect(page.locator("[data-segment-id=radio-segment]")).to_be_visible()

def test_r1_device_loss_exit_and_leave_while_talking(page):
    boot(page,surface="radio",connected=False)
    page.locator(".radio-ptt").click()
    page.wait_for_function("GroupV3Runtime.snapshot().media_connected")
    page.evaluate("()=>{window.__testMime='audio/mp4';"+RECORDER+"}")
    page.locator(".radio-ptt").click()
    expect(page.locator(".radio-ptt")).to_have_attribute("data-action","stop-radio")
    page.evaluate("GroupV3Runtime.getLocalAudioTrack().dispatchEvent(new Event('ended'))")
    expect(page.locator(".radio-recovery")).to_be_visible()
    page.locator(".radio-room-header [data-action=leave-radio]").click()
    page.wait_for_url("**/group/chat")
    page.locator("[data-surface=radio]:visible").click()
    page.locator(".radio-ptt").click()
    page.wait_for_function("GroupV3Runtime.snapshot().media_connected")
    page.locator(".radio-ptt").click()
    expect(page.locator(".radio-ptt")).to_have_attribute("data-action","stop-radio")
    page.once("dialog",lambda dialog:dialog.accept())
    page.locator(".radio-room-dock [data-action=leave-radio]").click()
    page.wait_for_url("**/group/chat")

def test_r1_old_radio_translation_url_alias_and_unified_settings(page):
    boot(page,surface="radio-translation",connected=False)
    page.wait_for_url("**/group/chat-translation?tab=radio")
    expect(page.locator("[data-surface=radio-translation]")).to_have_count(0)
    expect(page.locator("[data-action=history-tab][data-tab=radio]")).to_have_attribute("aria-pressed","true")
    expect(page.locator("[data-form=save-profile]")).to_have_count(1)
    expect(page.locator("[data-action=toggle-auto-translate]")).to_have_count(0)
    expect(page.locator(".mobile-language-bar")).to_have_count(0)


def boot(page, surface="video", connected=True, locale="vi", participant_count=2, has_session=True,
         output_supported=True, spaces=None, blocked_audio=False, defer_connect=False,
         auto_read=False, auto_translate=False, connect_with_pointer=True,
         messages=None, chat_translations=None, notification_preferences=None,
         notification_destination=None,
         session_status="active", self_invite_status="joined",
         initiated_by_membership_id="m1"):
    media_kind = "video" if surface == "video" else "audio"
    spaces = spaces or [dict(id="s1", title="Điều phối QA", status="active", version=1)]
    messages = list(messages or [])
    chat_translations = list(chat_translations or [])
    notification_preferences = dict(notification_preferences or {
        "mode": "smart", "muted_until": None, "paused": False,
        "unread_count": 0, "last_seen_sequence": 0,
    })
    lifecycle = []
    page.expose_function("__qaLifecycle", lambda item: lifecycle.append(item))
    members = [dict(id="m1", principal_type="member", principal_id="42", principal_user_id="42",
        display_name="Nguyễn Minh", role="owner", status="active"),
        dict(id="m2", principal_type="member", principal_id="84", principal_user_id="84",
        display_name="Trần An", role="member", status="active")]
    people = [dict(id="p1", membership_id="m1", livekit_identity="owner", display_name="Nguyễn Minh", invite_status="joined", connection_status="connected", media_connected=True),
        dict(id="p2", membership_id="m2", livekit_identity="guest", display_name="Trần An", invite_status="joined", connection_status="connected", media_connected=True)]
    people[0]["invite_status"] = self_invite_status
    for index in range(2, participant_count):
        members.append(dict(id=f"m{index+1}", principal_type="member", principal_id=str(100+index), principal_user_id=str(100+index),
            display_name=f"QA {index}", role="member", status="active"))
        people.append(dict(id=f"p{index+1}", membership_id=f"m{index+1}", livekit_identity=f"guest{index}", display_name=f"QA {index}", invite_status="joined", connection_status="connected", media_connected=True))
    radio_people = [dict(p, status="joined", joined_at="2026-09-05T07:00:00Z") for p in people]
    radio_session = dict(id="r1", title="QA Radio", status="ready", participants=radio_people)
    radio_history = []
    radio_events = []
    session = dict(id="r1", media_kind=media_kind, title="QA Video" if media_kind == "video" else "QA Call",
        status=session_status, participants=people,
        initiated_by_membership_id=initiated_by_membership_id)
    profile = dict(spoken_language="vi", preferred_output_language="zh-TW",
        auto_translate_enabled=auto_translate, auto_read_enabled=auto_read)
    template = (ROOT / "app/templates/group_communication_v3.html").read_text(encoding="utf-8")
    # The external media SDK is the only replaced script. All Group scripts/CSS
    # and their production load order are unchanged.
    import re
    template = re.sub(r'<script src="https://cdn.jsdelivr.net[^<]+</script>', "", template)
    html = Environment().from_string(template).render(locale=locale, runtime_config={"locale":locale, "initial_surface":surface})
    qa_setup = (
        "<script>window.__qaMediaKind=" + json.dumps(media_kind) + ";"
        "window.__qaBlockedAudio=" + json.dumps(bool(blocked_audio)) + ";"
        "window.__qaDeferConnect=" + json.dumps(bool(defer_connect)) + ";"
        "window.__qaAudioUnlocked=false;</script>"
    )
    html = html.replace("</head>", qa_setup + "</head>")
    def handle(route):
        path = urlparse(route.request.url).path
        if path.startswith("/static/"):
            if path.endswith("/group_device_manager.js"):
                device_source = DEVICE if output_supported else DEVICE.replace(
                    "outputSelectionSupported:()=>true", "outputSelectionSupported:()=>false")
                return route.fulfill(content_type="application/javascript", body=device_source)
            file = ROOT / "app" / path.lstrip("/")
            if file.exists():
                return route.fulfill(path=str(file))
            return route.fulfill(status=204)
        if path == "/group" or path.startswith("/group/"):
            return route.fulfill(content_type="text/html", body=html)
        payload = {}
        if path == "/api/group/session":
            payload = dict(principal=dict(type="member", id="42", user_id="42", locale=locale), group_authorized=True, direct_available=False)
        elif path == "/api/group/spaces":
            payload = {"spaces":spaces}
        elif path.endswith("/memberships"): payload={"memberships":members}
        elif path.endswith("/messages"):
            payload={"messages":messages}
        elif path.endswith("/notifications/preferences"):
            if route.request.method == "PUT":
                update = route.request.post_data_json or {}
                notification_preferences["mode"] = update.get(
                    "mode", notification_preferences["mode"]
                )
                if "mute_for_minutes" in update:
                    minutes = int(update["mute_for_minutes"])
                    notification_preferences["paused"] = minutes < 0
                    notification_preferences["muted_until"] = (
                        None if minutes == 0 else "2026-09-08T00:00:00Z"
                    )
            payload={"preferences":notification_preferences}
        elif path.endswith("/notifications/read"):
            update = route.request.post_data_json or {}
            notification_preferences["last_seen_sequence"] = int(
                update.get("last_seen_sequence") or 0
            )
            notification_preferences["unread_count"] = 0
            payload={"preferences":notification_preferences}
        elif path.endswith("/translation/profile"):
            if route.request.method == "PUT": profile.update(route.request.post_data_json)
            payload={"profile":profile}
        elif path.endswith("/translation/consent"): payload={"consent":{"status":"granted"}}
        elif path.endswith("/translation/chat-history"):
            payload={"translations":chat_translations}
        elif path.endswith("/radio/sessions"): payload={"sessions":[radio_session]}
        elif path.endswith("/radio/room/join"): payload={"session":radio_session}
        elif path.endswith("/radio/history"): payload={"bursts":radio_history}
        elif path.endswith("/floor/acquire"):
            radio_events.append("acquire")
            payload={"floor_token":"floor-qa", "burst":{"id":"burst-qa","started_at":"2026-09-05T07:00:00Z","state":"talking"}}
        elif path.endswith("/floor/stop"):
            radio_events.append("release")
            payload={"burst":{"id":"burst-qa","state":"finalizing"}}
        elif path.endswith("/bursts/burst-qa/transcribe"):
            assert radio_events[-1] == "release", radio_events
            radio_events.append("stt")
            segment={"id":"radio-segment","runtime_kind":"radio","source_text":"Radio text fixture","source_language":"vi","author_view":True,"state":"FINAL","variants":[]}
            radio_history.append({"id":"burst-qa","state":"final","speaker_display_name":"Nguyễn Minh","started_at":"2026-09-05T07:00:00Z","segment":segment})
            payload={"segment":segment}
        elif path.endswith("/sessions"):
            payload={"sessions":[session] if has_session and "/spaces/s1/" in path else []}
        elif path.endswith("/radio/sessions/r1"): payload={"session":radio_session,"floor":None}
        elif path.endswith("/radio/sessions/r1/join"): payload={"session":session}
        elif path.endswith("/connection-state"): payload={"session":session}
        elif path.endswith("/leave"):
            lifecycle.append("leave")
            payload={"session":dict(session, status="active")}
        elif path.endswith("/media-grant"):
            payload={"grant":{"provider":"livekit-cloud","url":"wss://fixture.invalid","token":"fixture-only","participant_identity":"owner","media_kind":"audio" if "/radio/" in path else media_kind}}
        route.fulfill(content_type="application/json", body=json.dumps(payload))
    page.route("**/*", handle)
    entry_path = "/group/" + surface
    if notification_destination:
        entry_path = "/group?" + urlencode(notification_destination)
    page.goto("http://127.0.0.1:8765" + entry_path)
    expect(page.locator(".native-app")).to_be_visible()
    if connected:
        if connect_with_pointer:
            page.locator('.call-control-dock [data-action="connect-media"]').click()
            page.locator('[data-action="prepare-prejoin"]').click()
            page.locator('[data-action="confirm-prejoin"]').click()
        else:
            page.evaluate("document.querySelector('.call-control-dock [data-action=connect-media]').click()")
            page.evaluate("document.querySelector('[data-action=prepare-prejoin]').click()")
            page.wait_for_function("!document.querySelector('[data-action=confirm-prejoin]').disabled")
            page.evaluate("document.querySelector('[data-action=confirm-prejoin]').click()")
        page.wait_for_function("GroupV3Runtime.snapshot().media_connected")
        if media_kind == "video":
            expect(page.locator(".local-media")).to_have_count(1)
            expect(page.locator("video.remote-media")).to_have_count(1)
            page.wait_for_function("document.querySelector('video.remote-media').videoWidth > 0")
        else:
            expect(page.locator(".local-media")).to_have_count(0)
        expect(page.locator("audio.remote-media")).to_have_count(1)
    return {"session": session, "profile": profile, "lifecycle": lifecycle, "spaces": spaces}


def geometry(page):
    return page.evaluate("""() => Object.fromEntries(
      ['.native-mobile','.native-main','.surface-content','.video-call-layout','.video-stage','.video-grid',
       '.call-control-dock','.translation-dock','.translation-dock__bar','.translation-dock__body','.translation-safety-layer']
      .map(s=>{let n=document.querySelector(s);if(!n)return [s,null];let r=n.getBoundingClientRect(),c=getComputedStyle(n);
      return [s,{x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,rows:c.gridTemplateRows,
        columns:c.gridTemplateColumns,padding:c.padding,minHeight:c.minHeight,display:c.display}]}))""")


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844), (390, 667)])
def test_notification_destination_and_settings_are_exact_and_responsive(
    page, tmp_path, width, height
):
    page.set_viewport_size({"width": width, "height": height})
    target_message = {
        "id": "message-qa",
        "sequence": 7,
        "sender": {
            "type": "member",
            "id": "84",
            "user_id": "84",
            "display_name": "Trần An",
        },
        "content_type": "text",
        "content": "Nội dung chỉ được đọc trong AI-COMMUNICATION.",
        "source_language": "vi",
        "attachments": [],
        "pinned": False,
        "created_at": "2026-09-07T02:00:00Z",
    }
    boot(
        page,
        surface="chat",
        connected=False,
        spaces=[
            {"id": "s0", "title": "Nhóm mặc định", "status": "active", "version": 1},
            {"id": "s1", "title": "Điều phối QA", "status": "active", "version": 1},
        ],
        messages=[target_message],
        notification_preferences={
            "mode": "smart",
            "muted_until": None,
            "paused": False,
            "unread_count": 1,
            "last_seen_sequence": 0,
        },
        notification_destination={
            "space_id": "s1",
            "surface": "chat",
            "resource_id": "message-qa",
        },
    )

    expect(page.locator(".native-app")).to_have_attribute("data-state", "chat")
    assert page.evaluate("GroupV3Runtime.snapshot().space_id") == "s1"
    target = page.locator('[data-message-id="message-qa"]')
    expect(target).to_have_attribute("data-notification-target", "true")
    assert "space_id=s1" in page.url
    assert "resource_id=message-qa" in page.url

    page.locator('[data-action="settings"]').click()
    settings = page.locator(".group-settings")
    expect(settings).to_be_visible()
    expect(settings.locator(".group-notification-settings")).to_be_visible()
    assert settings.locator('[data-action="notification-mode"]').count() == 4
    assert settings.locator('[data-action="notification-mute"]').count() == 5
    if width <= 390:
        touch_targets = settings.locator(
            '[data-action="notification-mode"], '
            '[data-action="notification-mute"], '
            '.group-ringtone-preferences select'
        )
        assert all(
            touch_targets.nth(index).bounding_box()["height"] >= 44
            for index in range(touch_targets.count())
        )

    settings.locator('[data-action="notification-mode"][data-mode="all"]').click()
    page.wait_for_function(
        """() => document.querySelector(
          '[data-action="notification-mode"][data-mode="all"]'
        )?.classList.contains('action-primary')"""
    )
    settings.locator('[data-action="notification-mute"][data-minutes="15"]').click()
    expect(settings.locator('[data-action="notification-mute"][data-minutes="0"]')).to_be_visible()

    settings.locator('[data-change="ringtone-volume"]').select_option("25")
    settings.locator('[data-change="ringtone-duration"]').select_option("15")
    stored = page.evaluate(
        "JSON.parse(localStorage.getItem('groupV3RingtonePreferences'))"
    )
    assert stored["incoming_ringtone_volume_percent"] == 25
    assert stored["incoming_ringtone_duration_seconds"] == 15

    box = settings.bounding_box()
    assert box is not None
    assert box["x"] >= 0 and box["y"] >= 0
    assert box["x"] + box["width"] <= width + 1
    assert box["y"] + box["height"] <= height + 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    scroll = settings.locator(".member-manager-scroll")
    scroll_metrics = scroll.evaluate(
        "node => ({clientWidth: node.clientWidth, scrollWidth: node.scrollWidth, "
        "clientHeight: node.clientHeight, scrollHeight: node.scrollHeight})"
    )
    assert scroll_metrics["scrollWidth"] <= scroll_metrics["clientWidth"] + 1
    last_action = settings.locator('[data-action="delete-group"]')
    last_action.scroll_into_view_if_needed()
    last_box = last_action.bounding_box()
    assert last_box is not None and last_box["y"] + last_box["height"] <= height + 1
    if scroll_metrics["scrollHeight"] > scroll_metrics["clientHeight"] + 1:
        assert scroll.evaluate("node => node.scrollTop") > 0
    page.screenshot(
        path=str(tmp_path / f"group-notifications-{width}x{height}.png"),
        animations="disabled",
    )


def test_chat_history_translation_never_auto_reads_when_auto_read_is_enabled(page):
    message = {
        "id": "chat-history-message",
        "sequence": 8,
        "sender": {
            "type": "member",
            "id": "84",
            "user_id": "84",
            "display_name": "Trần An",
        },
        "content_type": "text",
        "content": "Nội dung gốc trong lịch sử Chat",
        "source_language": "vi",
        "attachments": [],
        "pinned": False,
        "created_at": "2026-09-07T02:00:00Z",
    }
    translation = {
        "id": "chat-history-translation",
        "message_id": message["id"],
        "source_language": "vi",
        "target_language": "zh-TW",
        "state": "FINAL",
        "translated_text": "聊天歷史翻譯",
        "shared_variant": True,
    }
    boot(
        page,
        surface="chat",
        connected=False,
        auto_read=True,
        messages=[message],
        chat_translations=[translation],
    )

    expect(page.locator('[data-message-id="chat-history-message"]')).to_contain_text(
        "聊天歷史翻譯"
    )
    assert page.evaluate("window.__spoken") == []
    page.evaluate(
        """() => window.__eventSources[0].emit('group-change', {
          type: 'translation.chat.final',
          space_id: 's1',
          resource_id: 'chat-history-message'
        })"""
    )
    page.wait_for_timeout(200)
    expect(page.locator('[data-message-id="chat-history-message"]')).to_contain_text(
        "聊天歷史翻譯"
    )
    assert page.evaluate("window.__spoken") == []


@pytest.mark.parametrize("width,height", [(390,844),(844,390),(412,915)])
def test_mobile_geometry_and_panel_modes(page, tmp_path, width, height):
    page.set_viewport_size({"width":width,"height":height})
    boot(page)
    g = geometry(page)
    assert g[".native-main"]["y"] >= 8, g
    assert g[".surface-content"]["height"] == height - 8, g
    assert g[".translation-dock"]["height"] <= 64, g
    assert g[".translation-dock"]["bottom"] == height, g
    assert g[".translation-safety-layer"]["display"] == "none", g
    buttons = page.locator(".call-control-dock > .action-button")
    boxes = [buttons.nth(i).bounding_box() for i in range(4)]
    assert len({round(b["y"]) for b in boxes}) == 1, boxes
    assert all(b["width"] >= 44 and b["height"] >= 44 for b in boxes)
    page.screenshot(path=str(tmp_path / f"{width}x{height}-collapsed.png"))
    counts = page.evaluate("({...__mediaCounts})")
    for mode in ["HALF", "FULL"]:
        page.locator('[data-workspace-action="translation-plus"]').click()
        expect(page.locator(".translation-dock")).to_have_attribute("data-translation-mode", mode)
        expect(page.locator("[data-v2-text]")).to_be_visible()
        assert page.locator(".translation-dock").bounding_box()["y"] >= 0
        page.screenshot(path=str(tmp_path / f"{width}x{height}-{mode}.png"))
    page.locator('[data-workspace-action="translation-minus"]').click()
    page.locator('[data-workspace-action="translation-minus"]').click()
    assert page.evaluate("({...__mediaCounts})") == counts
    (tmp_path / "geometry.json").write_text(json.dumps(g, indent=2), encoding="utf-8")


def test_desktop_arbitration_and_stable_media_panel_dom(page, tmp_path):
    page.set_viewport_size({"width":1440,"height":900})
    boot(page)
    page.evaluate("window.__savedPanel=document.querySelector('[data-group-translation-v2]');window.__savedVideo=document.querySelector('.remote-media')")
    page.locator('[data-workspace-action="video-plus"]').click()
    page.locator('[data-workspace-action="translation-plus"]').click()
    expect(page.locator(".video-call-layout")).to_have_attribute("data-video-mode","STANDARD")
    expect(page.locator(".translation-dock")).to_have_attribute("data-translation-mode","HALF")
    page.wait_for_function("document.querySelector('.translation-dock').getBoundingClientRect().width >= 320")
    page.locator('[data-workspace-action="translation-plus"]').click()
    expect(page.locator(".translation-dock")).to_have_attribute("data-translation-mode","FULL")
    page.locator('[data-workspace-action="translation-minus"]').click()
    page.locator('[data-workspace-action="translation-minus"]').click()
    expect(page.locator(".video-call-layout")).to_have_attribute("data-video-mode","MAXIMIZED")
    page.locator('[data-action="refresh"]').click()
    page.wait_for_function("document.querySelector('#group-native-app').getAttribute('aria-busy') === null")
    assert page.evaluate("__savedPanel===document.querySelector('[data-group-translation-v2]') && __savedVideo===document.querySelector('.remote-media')")
    assert page.evaluate("__mediaCounts.attach") == 1
    page.screenshot(path=str(tmp_path / "desktop-max-closed.png"), animations="disabled")
    page.locator('[data-workspace-action="translation-plus"]').click()
    page.wait_for_function("document.querySelector('.translation-dock').getBoundingClientRect().width >= 320")
    expect(page.locator(".video-compact-summary")).to_be_hidden()
    page.screenshot(path=str(tmp_path / "desktop-standard-open.png"), animations="disabled")


def test_sse_refresh_cannot_replace_or_disconnect_inflight_video_connect(page):
    context = boot(page, connected=False, defer_connect=True)
    pending = []

    def hold_stale_sessions(route):
        pending.append(route)

    page.route("**/api/group/spaces/s1/sessions?limit=50", hold_stale_sessions)
    page.evaluate("""() => __eventSources[0].emit('group-change', {
      space_id:'s1',type:'media_session.connection_state',resource_id:'r1'
    })""")
    for _ in range(20):
        if pending:
            break
        page.wait_for_timeout(25)
    assert len(pending) == 1

    page.locator('.call-control-dock [data-action="connect-media"]').click()
    page.locator('[data-action="prepare-prejoin"]').click()
    page.locator('[data-action="confirm-prejoin"]').click()
    page.wait_for_function("__mediaCounts.connect === 1")

    stale_people = []
    for person in context["session"]["participants"]:
        stale = dict(person, invite_status="invited", connection_status="not_connected")
        stale.pop("media_connected", None)
        stale_people.append(stale)
    stale_session = dict(context["session"], status="ringing", participants=stale_people)
    pending[0].fulfill(
        content_type="application/json",
        body=json.dumps({"sessions": [stale_session]}),
    )
    page.wait_for_timeout(50)
    assert page.evaluate("GroupV3Runtime.snapshot().runtime_id") == "r1"
    page.evaluate("() => {__qaDeferConnect=false;__qaReleaseConnect();}")
    page.wait_for_function("GroupV3Runtime.snapshot().media_connected")

    counts = page.evaluate("({...__mediaCounts})")
    assert counts["rooms"] == 1
    assert counts["connect"] == 1
    assert counts["publish"] == 2
    assert counts["disconnect"] == 0
    assert page.evaluate("GroupV3Runtime.snapshot().runtime_id") == "r1"
    assert page.locator(".video-call-layout").count() == 1


@pytest.mark.parametrize("auto_translate", [False, True], ids=["translation-off", "translation-on"])
def test_radio_raw_audio_is_attached_and_audible_with_translation_modes(page, auto_translate):
    boot(
        page,
        surface="radio",
        connected=False,
        auto_translate=auto_translate,
        auto_read=auto_translate,
    )
    page.evaluate("""() => {
      window.__spoken=[];speechSynthesis.cancel=()=>{};
      speechSynthesis.speak=utterance=>{if(utterance.text!=='\u200b')__spoken.push(utterance.text);
        queueMicrotask(()=>{utterance.onstart?.();utterance.onend?.();});};
    }""")
    page.locator(".radio-ptt").click()
    page.wait_for_function("GroupV3Runtime.snapshot().media_connected")
    expect(page.locator("audio.remote-media")).to_have_count(1)
    assert page.evaluate("document.querySelector('audio.remote-media').muted") is False
    counts = page.evaluate("({...__mediaCounts})")
    assert counts["audioAttach"] == 1
    assert counts["audioPlay"] >= 1
    assert counts["acquire"] == 0

    if auto_translate:
        segment = {
            "id": "radio-live-final",
            "state": "FINAL",
            "translated_text": "Bản dịch Radio",
            "source_text": "Radio raw source",
            "created_at": "2026-09-06T00:00:01Z",
            "speaker_membership_id": "m2",
            "display_language": "vi",
            "target_language": "vi",
            "author_view": False,
        }
        page.evaluate("""() => window.dispatchEvent(new CustomEvent('group-v3:translation-segment',
          {detail:{type:'translation.segment.changed',resource_id:'radio-live-final'}}))""")
        page.evaluate(
            "segment => GroupV3TranslationController.readRadioHistory([segment])",
            segment,
        )
        page.wait_for_function("__spoken.includes('Bản dịch Radio')")
        assert page.evaluate("__mediaCounts.audioAttach") == 1


def test_radio_blocked_audio_exposes_and_recovers_with_explicit_control(page):
    boot(page, surface="radio", connected=False, blocked_audio=True)
    page.locator(".radio-ptt").click()
    page.wait_for_function("GroupV3Runtime.snapshot().media_connected")
    expect(page.locator(".media-audio-recovery")).to_be_visible()
    expect(page.locator('[data-action="enable-room-audio"]')).to_be_visible()
    page.locator('[data-action="enable-room-audio"]').click()
    page.wait_for_function("__mediaCounts.startAudio === 1")
    expect(page.locator(".media-audio-recovery")).to_have_count(0)
    assert page.evaluate("__mediaCounts.audioPlay") >= 2


@pytest.mark.parametrize("surface", ["call", "video"])
@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_call_video_room_picker_switches_after_semantic_leave(page, surface, width, height):
    page.set_viewport_size({"width": width, "height": height})
    context = boot(
        page,
        surface=surface,
        spaces=[
            dict(id="s1", title="Điều phối QA", status="active", version=1),
            dict(id="s2", title="Không gian thứ hai", status="active", version=1),
        ],
    )
    toggle = page.locator(".active-media-room-button:visible")
    expect(toggle).to_be_visible()
    toggle_box = toggle.bounding_box()
    assert toggle_box["width"] >= 44 and toggle_box["height"] >= 44
    toggle.click()
    target = page.locator('.media-room-picker-row[data-id="s2"]')
    expect(target).to_be_visible()
    target_box = target.bounding_box()
    assert target_box["height"] >= 44
    page.once("dialog", lambda dialog: dialog.accept())
    target.click()
    page.wait_for_function("GroupV3Runtime.snapshot().space_id === 's2'")
    page.wait_for_timeout(50)
    assert context["lifecycle"][:2] == ["leave", "disconnect"]
    assert page.evaluate("__mediaCounts.disconnect") == 1
    expect(page.locator(".media-start-intro")).to_be_visible()


def test_active_media_space_switch_aborts_before_disconnect_when_leave_fails(page):
    page.set_viewport_size({"width": 390, "height": 844})
    boot(
        page,
        surface="video",
        spaces=[
            dict(id="s1", title="Điều phối QA", status="active", version=1),
            dict(id="s2", title="Không gian thứ hai", status="active", version=1),
        ],
    )
    page.route(
        "**/api/group/spaces/s1/sessions/r1/leave",
        lambda route: route.fulfill(
            status=500,
            content_type="application/json",
            body='{"detail":"leave_failed"}',
        ),
    )
    page.locator(".active-media-room-button:visible").click()
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator('.media-room-picker-row[data-id="s2"]').click()
    page.wait_for_timeout(100)
    assert page.evaluate("GroupV3Runtime.snapshot().space_id") == "s1"
    assert page.evaluate("__mediaCounts.disconnect") == 0
    assert page.evaluate("GroupV3Runtime.snapshot().media_connected") is True


@pytest.mark.parametrize("surface", ["call", "video"])
@pytest.mark.parametrize("width,height", [(390, 844), (390, 667), (844, 390)])
def test_mobile_media_start_reserves_intro_form_and_cta(page, surface, width, height):
    page.set_viewport_size({"width": width, "height": height})
    boot(page, surface=surface, connected=False, participant_count=8, has_session=False)
    intro = page.locator(".media-start-intro")
    form = page.locator(".media-start-form")
    action = form.locator("button[type=submit]")
    expect(intro.locator("span").first).to_be_visible()
    expect(intro.locator("h2")).to_be_visible()
    expect(intro.locator("p")).to_be_visible()
    expect(form).to_be_visible()
    intro_box = intro.bounding_box()
    form_box = form.bounding_box()
    action_box = action.bounding_box()
    nav_box = page.locator(".mobile-bottom-nav").bounding_box()
    if height > 500:
        assert form_box["y"] >= intro_box["y"] + intro_box["height"] + 12
    else:
        assert form_box["x"] >= intro_box["x"] + intro_box["width"] + 10
    assert action_box["height"] >= 44
    assert action_box["y"] + action_box["height"] <= nav_box["y"] + 1
    assert page.evaluate("getComputedStyle(document.querySelector('.media-member-list')).overflowY") in {"auto", "scroll"}
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


RECORDER = """
window.__recorderOptions=[];window.__recorders=0;
window.MediaRecorder=class extends EventTarget {
 static isTypeSupported(mime){return mime===window.__testMime;}
 constructor(stream,options){super();this.state='inactive';this.mimeType=options?.mimeType||__testMime;
   __recorderOptions.push(options);this.stream=stream;__recorders++;}
 start(){this.state='recording';}
 stop(){this.state='inactive';queueMicrotask(()=>{
   if(window.__emptyAudio!==true)this.dispatchEvent(new MessageEvent('dataavailable',{data:new Blob(['fixture audio'],{type:this.mimeType})}));
   this.dispatchEvent(new Event('stop'));
 });}
};
"""


def voice_setup(page, mime="audio/mp4", surface="video", width=390, height=844):
    page.set_viewport_size({"width": width, "height": height})
    boot(page, surface=surface)
    page.evaluate("(mime)=>window.__testMime=mime", mime)
    page.evaluate("() => {" + RECORDER + "}")
    page.locator('[data-workspace-action="translation-plus"]').click()
    return page.locator('[data-v2-action="record"]')


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_call_translation_reuses_group_track_and_uses_call_runtime(page, width, height):
    button = voice_setup(page, surface="call", width=width, height=height)
    expect(page.locator(".call-communication-layout .translation-dock")).to_be_visible()
    snapshot = page.evaluate("GroupV3Runtime.snapshot()")
    assert snapshot["runtime_kind"] == "call"
    assert snapshot["runtime_id"] == "r1"
    expect(page.locator(".native-app")).to_have_attribute("data-runtime-key", "call:r1")

    text_requests = []
    voice_requests = []
    text_segment = {
        "id": "call-text",
        "runtime_kind": "call",
        "source_language": "vi",
        "source_text": "Xin chào Call",
        "state": "FINAL",
        "author_view": True,
        "variants": [],
    }
    voice_segment = dict(text_segment, id="call-voice", source_text="Ghi âm Call")

    def submit_text(route):
        text_requests.append(route.request.post_data_json)
        route.fulfill(
            content_type="application/json",
            body=json.dumps({"segment": text_segment}),
        )

    def submit_voice(route):
        voice_requests.append(route.request.post_data_buffer)
        route.fulfill(
            content_type="application/json",
            body=json.dumps({"segment": voice_segment}),
        )

    page.route("**/translation/segments/text", submit_text)
    page.route("**/translation/segments/voice", submit_voice)
    page.locator("[data-v2-text]").fill("Xin chào Call")
    page.locator('[data-v2-action="send"]').click()
    expect(page.locator('[data-segment-id="call-text"]')).to_be_visible()
    assert len(text_requests) == 1
    assert text_requests[0]["runtime_kind"] == "call"
    assert text_requests[0]["runtime_id"] == "r1"
    assert text_requests[0]["client_segment_id"]
    assert text_requests[0]["source_language"] == "vi"
    assert text_requests[0]["source_text"] == "Xin chào Call"

    acquire_before = page.evaluate("__mediaCounts.acquire")
    button.click()
    expect(button).to_have_attribute("data-voice-icon", "save")
    button.click()
    expect(page.locator('[data-segment-id="call-voice"]')).to_be_visible()
    assert page.evaluate("__mediaCounts.acquire") == acquire_before == 1
    assert len(voice_requests) == 1
    assert b'\r\n\r\ncall\r\n' in voice_requests[0]
    assert b'\r\n\r\nr1\r\n' in voice_requests[0]

    page.locator('[data-workspace-action="translation-plus"]').click()
    expect(page.locator(".translation-dock")).to_have_attribute("data-translation-mode", "FULL")
    page.locator('[data-workspace-action="translation-minus"]').click()
    page.locator('[data-workspace-action="translation-minus"]').click()
    expect(page.locator(".translation-dock")).to_have_attribute("data-translation-mode", "COLLAPSED")


@pytest.mark.parametrize("mime,extension", [("audio/mp4","m4a"),("audio/webm;codecs=opus","webm"),("audio/ogg;codecs=opus","ogg")])
def test_voice_save_mime_and_history_failure_keeps_result(page, mime, extension):
    button = voice_setup(page, mime)
    uploads = []
    result = {"id":"seg1","source_language":"vi","source_text":"Canonical fixture","state":"FINAL","author_view":True,"variants":[]}
    def upload(route):
        uploads.append(route.request.post_data_buffer)
        route.fulfill(content_type="application/json",body=json.dumps({"segment":result}))
    page.route("**/translation/segments/voice", upload)
    page.route("**/translation/v2-history?*", lambda r:r.fulfill(status=503,content_type="application/json",body='{"detail":"history_unavailable"}'))
    button.click()
    expect(button).to_have_attribute("data-voice-icon","save")
    expect(button).to_have_attribute("aria-pressed","true")
    # A normal shell refresh must not dispose a recording.
    page.evaluate("document.querySelector('[data-action=refresh]').click()")
    page.wait_for_function("!document.querySelector('#group-native-app').hasAttribute('aria-busy')")
    expect(button).to_have_attribute("data-voice-icon","save")
    button.click()
    expect(page.locator("[data-segment-id=seg1]")).to_be_visible()
    expect(button).to_have_attribute("data-voice-icon","mic")
    expect(page.locator("[data-v2-warning]")).to_be_visible()
    expect(page.locator("[data-v2-error]")).to_be_hidden()
    assert len(uploads) == 1 and f'group-translation.{extension}'.encode() in uploads[0]
    assert b'duration_seconds' in uploads[0] and mime.encode() in uploads[0]
    assert page.evaluate("GroupV3Runtime.getLocalAudioTrack().readyState") == "live"
    assert page.evaluate("__mediaCounts.acquire") == 1
    assert not any("Canonical fixture" in json.dumps(row) for row in page.evaluate("GroupV3TranslationController.diagnostics()"))


def test_empty_audio_and_muted_mic_are_visible_errors(page):
    button = voice_setup(page)
    page.evaluate("window.__emptyAudio=true")
    button.click()
    expect(button).to_have_attribute("data-voice-icon","save")
    button.click()
    expect(page.locator("[data-v2-error]")).to_have_attribute("data-error-category","EMPTY_AUDIO_ERROR")
    page.evaluate("GroupV3Runtime.getLocalAudioTrack().enabled=false")
    button.click()
    expect(page.locator("[data-v2-error]")).to_have_attribute("data-error-category","RECORDING_ERROR")
    assert page.evaluate("__recorders") == 1


def test_exact_remote_identity_waits_until_tile_exists(page):
    boot(page)
    page.evaluate("""() => {
      const stream=__makeStream();
      window.__lateTrack={kind:'video',sid:'late',mediaStreamTrack:stream.getVideoTracks()[0],
        attach(){__mediaCounts.attach++;const node=document.createElement('video');node.muted=true;node.srcObject=stream;return node;},detach(){return []}};
      GroupMediaPresentation.remote(__lateTrack,'late-person');
    }""")
    assert page.evaluate("__mediaCounts.attach") == 1
    page.evaluate("""() => {
      const tile=document.createElement('article');tile.className='video-tile';tile.dataset.videoIdentity='late-person';
      document.querySelector('.video-grid').append(tile);GroupMediaPresentation.sync();GroupMediaPresentation.sync();
    }""")
    expect(page.locator('[data-video-identity="late-person"] video')).to_have_count(1)
    assert page.evaluate("__mediaCounts.attach") == 2


@pytest.mark.parametrize("stage,category", [("profile","PROFILE_ERROR"),("voice","STT_ERROR")])
def test_voice_request_failure_is_classified(page, stage, category):
    button = voice_setup(page)
    path = "**/translation/profile" if stage == "profile" else "**/translation/segments/voice"
    page.route(path, lambda r:r.fulfill(status=503,content_type="application/json",body='{"detail":"provider_temporarily_unavailable"}'))
    button.click()
    if stage == "voice":
        expect(button).to_have_attribute("data-voice-icon","save")
        button.click()
    expect(page.locator("[data-v2-error]")).to_have_attribute("data-error-category",category)
    expect(button).to_have_attribute("data-voice-icon","mic")
    if stage == "profile": assert page.evaluate("__recorders") == 0


def test_record_double_click_during_profile_save_is_single_capture(page):
    button = voice_setup(page)
    page.evaluate("""() => {
      const b=document.querySelector('[data-v2-action="record"]');
      b.dispatchEvent(new Event('click'));b.dispatchEvent(new Event('click'));
    }""")
    expect(button).to_have_attribute("data-voice-icon","save")
    assert page.evaluate("__recorders") == 1


def test_radio_room_join_has_one_ptt_and_no_microphone_or_text_composer(page, tmp_path):
    requests=[]
    page.on("request", lambda request:requests.append(request.url))
    boot(page, surface="radio", connected=False)
    page.locator('.radio-ptt').click()
    page.wait_for_function("GroupV3Runtime.snapshot().media_connected")
    expect(page.locator(".radio-ptt")).to_have_count(1)
    expect(page.locator(".radio-ptt")).to_have_attribute("data-action","start-radio")
    expect(page.locator(".radio-room textarea")).to_have_count(0)
    expect(page.locator(".radio-room [data-v2-panel]")).to_have_count(0)
    assert not any("/floor/" in url for url in requests)
    assert page.evaluate("__mediaCounts.acquire") == 0
    page.screenshot(path=str(tmp_path / "radio-room-ready.png"))


def test_focus_hide_restore_never_republishes_or_reattaches(page):
    boot(page)
    counts=page.evaluate("({...__mediaCounts})")
    page.locator('.video-tile [data-video-focus=guest]').click()
    expect(page.locator('[data-video-identity=owner]')).to_be_hidden()
    page.locator('.video-tile [data-video-focus=guest]').click()
    expect(page.locator('[data-video-identity=owner]')).to_be_visible()
    page.locator('.video-tile [data-video-hide=guest]').click()
    expect(page.locator('[data-video-identity=guest]')).to_be_hidden()
    page.locator('[data-action=toggle-participant-drawer]').click()
    page.locator('[data-video-restore=guest]').click()
    expect(page.locator('[data-video-identity=guest]')).to_be_visible()
    assert page.evaluate("({...__mediaCounts})") == counts


def test_partial_voice_has_variant_error_and_no_duplicate_source(page):
    button=voice_setup(page)
    item={"id":"partial1","source_language":"vi","source_text":"Source only once","author_view":True,"state":"PARTIAL",
        "variants":[{"target_language":"vi","translated_text":"Source only once","state":"FINAL","recipient_count":0},
        {"target_language":"zh-TW","translated_text":None,"state":"FAILED","recipient_count":1}]}
    page.route("**/translation/segments/voice",lambda r:r.fulfill(content_type="application/json",body=json.dumps({"segment":item})))
    button.click()
    expect(button).to_have_attribute("data-voice-icon","save")
    button.click()
    expect(page.locator("[data-v2-error]")).to_have_attribute("data-error-category","TRANSLATION_VARIANT_ERROR")
    expect(page.locator('[data-variant-language=vi]')).to_have_count(0)
    expect(page.locator('[data-segment-id=partial1] [data-v2-retry]')).to_be_visible()


def test_history_bootstrap_never_auto_reads_and_manual_play_is_explicit(page):
    voice_setup(page)
    page.evaluate("""() => {window.__spoken=[];speechSynthesis.speak=u=>{__spoken.push(u.text);queueMicrotask(()=>{u.onstart?.();u.onend?.();});};speechSynthesis.cancel=()=>{};}""")
    page.locator("[data-v2-auto-read]").check()
    page.wait_for_function("GroupV3Runtime.snapshot().auto_read")
    item={"id":"received1","state":"FINAL","translated_text":"Translated fixture","source_text":"Original",
        "speaker_membership_id":"m2","display_language":"zh-TW","target_language":"zh-TW","author_view":False}
    page.route("**/translation/v2-history?*",lambda r:r.fulfill(content_type="application/json",body=json.dumps({"segments":[item]})))
    before=page.evaluate("__mediaCounts.publish")
    for _ in range(2):
        page.evaluate("GroupV3TranslationController.loadHistory(document.querySelector('[data-group-translation-v2]'))")
    assert page.evaluate("__spoken") == []
    page.evaluate("""() => window.dispatchEvent(new CustomEvent('group-v3:translation-segment',
      {detail:{type:'translation.segment.history_changed',resource_id:'received1'}}))""")
    page.wait_for_timeout(50)
    assert page.evaluate("__spoken") == []
    page.locator("[data-segment-id=received1] [data-v2-play]").click()
    page.wait_for_function("__spoken.length === 1")
    assert page.evaluate("__spoken") == ["Translated fixture"]
    assert page.evaluate("__mediaCounts.publish") == before


def test_new_realtime_final_auto_reads_once_after_invalidation(page):
    voice_setup(page)
    page.evaluate("""() => {window.__spoken=[];speechSynthesis.speak=u=>{__spoken.push(u.text);queueMicrotask(()=>{u.onstart?.();u.onend?.();});};speechSynthesis.cancel=()=>{};}""")
    page.locator("[data-v2-auto-read]").check()
    item={"id":"realtime-final","state":"FINAL","translated_text":"Realtime fixture","source_text":"Original",
        "speaker_membership_id":"m2","display_language":"zh-TW","target_language":"zh-TW","author_view":False}
    page.route("**/translation/v2-history?*",lambda r:r.fulfill(content_type="application/json",body=json.dumps({"segments":[item]})))
    page.evaluate("""() => window.dispatchEvent(new CustomEvent('group-v3:translation-segment',
      {detail:{type:'translation.segment.changed',resource_id:'realtime-final'}}))""")
    page.wait_for_function("__spoken.length === 1")
    page.evaluate("GroupV3TranslationController.loadHistory(document.querySelector('[data-group-translation-v2]'))")
    page.wait_for_timeout(50)
    assert page.evaluate("__spoken") == ["Realtime fixture"]


def test_first_autoread_final_waits_for_activation_and_consumes_only_onstart(page):
    boot(page, connected=True, auto_read=True, connect_with_pointer=False)
    # Programmatic expansion deliberately avoids a pointer gesture so the test
    # begins in the same LOCKED state as a freshly opened mobile runtime.
    page.evaluate("document.querySelector('[data-workspace-action=translation-plus]').click()")
    page.evaluate("""() => {
      window.__spoken=[];window.__pendingUtterance=null;
      speechSynthesis.cancel=()=>{};
      speechSynthesis.speak=utterance=>{__spoken.push(utterance.text);__pendingUtterance=utterance;};
    }""")
    item = {
        "id": "first-autoread-final",
        "state": "FINAL",
        "translated_text": "Bản dịch đầu tiên",
        "source_text": "First source",
        "created_at": "2026-09-06T00:00:01Z",
        "speaker_membership_id": "m2",
        "display_language": "vi",
        "target_language": "vi",
        "author_view": False,
    }
    page.route(
        "**/translation/v2-history?*",
        lambda route: route.fulfill(
            content_type="application/json",
            body=json.dumps({"segments": [item]}),
        ),
    )
    page.evaluate("""() => window.dispatchEvent(new CustomEvent('group-v3:translation-segment',
      {detail:{type:'translation.segment.changed',resource_id:'first-autoread-final'}}))""")
    page.wait_for_function("GroupV3TtsManager.state() === 'UNLOCK_REQUIRED'")
    assert page.evaluate("__spoken") == []
    diagnostics = page.evaluate("GroupV3TtsManager.diagnostics()")
    assert len(diagnostics["queued"]) == 1
    assert not any("first-autoread-final" in key for key in diagnostics["startedKeys"])
    expect(page.locator("[data-v2-error]")).to_have_attribute(
        "data-error-category", "TTS_PLAYBACK_STATE"
    )
    assert "không hỗ trợ" not in page.locator("[data-v2-error]").inner_text().lower()

    page.locator(".call-status-line > span").first.click()
    page.wait_for_function("__spoken.length === 1")
    assert page.evaluate("__spoken") == ["Bản dịch đầu tiên"]
    assert not any(
        "first-autoread-final" in key
        for key in page.evaluate("GroupV3TtsManager.diagnostics().startedKeys")
    )
    page.evaluate("__pendingUtterance.onstart()")
    page.wait_for_function("GroupV3TtsManager.diagnostics().startedKeys.some(k=>k.includes('first-autoread-final'))")
    page.evaluate("__pendingUtterance.onend()")
    expect(page.locator("[data-v2-error]")).to_be_hidden()


def test_autoread_queues_all_finals_and_consumes_only_after_onstart(page):
    voice_setup(page)
    items = [
        {"id":f"received-{index}","state":"FINAL","translated_text":text,"source_text":"Original",
         "created_at":f"2026-09-06T00:00:0{index}Z","speaker_membership_id":"m2",
         "display_language":"zh-TW","target_language":"zh-TW","author_view":False}
        for index, text in enumerate(["Bản A", "Bản B", "Bản C"], 1)
    ]
    page.route("**/translation/v2-history?*", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"segments":items})))
    page.evaluate("""() => {
      window.__spoken=[];
      speechSynthesis.speak=utterance=>{__spoken.push(utterance.text);queueMicrotask(()=>{
        utterance.onstart?.();utterance.onend?.();
      });};
      speechSynthesis.cancel=()=>{};
    }""")
    page.locator("[data-v2-auto-read]").check()
    page.evaluate("""ids => ids.forEach(id => window.dispatchEvent(new CustomEvent('group-v3:translation-segment',
      {detail:{type:'translation.segment.changed',resource_id:id}})))""", [item["id"] for item in items])
    page.wait_for_function("__spoken.length === 3")
    assert page.evaluate("__spoken") == ["Bản A", "Bản B", "Bản C"]
    assert len(page.evaluate("GroupV3TtsManager.diagnostics().startedKeys.filter(k=>k.includes('received-'))")) == 3


def test_autoread_disabled_history_stays_manual_when_enabled(page):
    voice_setup(page)
    item = {"id":"disabled-bootstrap","state":"FINAL","translated_text":"Play after enable",
        "source_text":"Original","created_at":"2026-09-06T00:00:01Z","speaker_membership_id":"m2",
        "display_language":"en","target_language":"en","author_view":False}
    page.route("**/translation/v2-history?*", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"segments":[item]})))
    page.evaluate("""() => {window.__spoken=[];speechSynthesis.cancel=()=>{};speechSynthesis.speak=u=>{
      __spoken.push(u.text);queueMicrotask(()=>{u.onstart?.();u.onend?.();});};}""")
    page.evaluate("GroupV3TranslationController.loadHistory(document.querySelector('[data-group-translation-v2]'))")
    page.wait_for_timeout(50)
    assert page.evaluate("__spoken") == []
    page.locator("[data-v2-auto-read]").check()
    page.wait_for_timeout(100)
    assert page.evaluate("__spoken") == []


def test_autoread_start_timeout_is_retryable_and_manual_tts_is_deterministic(page):
    voice_setup(page)
    item = {"id":"retryable-final","state":"FINAL","translated_text":"Retry me","source_text":"Original",
        "created_at":"2026-09-06T00:00:01Z","speaker_membership_id":"m2",
        "display_language":"en","target_language":"en","author_view":False}
    page.route("**/translation/v2-history?*", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"segments":[item]})))
    page.evaluate("""() => {
      GroupV3TtsManager.configureForTests({startTimeoutMs:60,voiceWaitMs:0});
      window.__speakAttempts=0;window.__spoken=[];
      speechSynthesis.cancel=()=>{};
      speechSynthesis.speak=utterance=>{
        __speakAttempts++;
        if(__speakAttempts===1)return;
        __spoken.push(utterance.text);queueMicrotask(()=>{utterance.onstart?.();utterance.onend?.();});
      };
    }""")
    page.locator("[data-v2-auto-read]").check()
    page.evaluate("""() => window.dispatchEvent(new CustomEvent('group-v3:translation-segment',
      {detail:{type:'translation.segment.changed',resource_id:'retryable-final'}}))""")
    page.wait_for_function("__speakAttempts === 1")
    page.wait_for_timeout(100)
    page.locator(".call-status-line > span").first.click()
    page.wait_for_function("__spoken.length === 1")
    assert page.evaluate("__speakAttempts") == 2
    page.evaluate("""() => {
      window.__insideManualClick=false;window.__manualWasSynchronous=false;
      speechSynthesis.speak=utterance=>{__manualWasSynchronous=__insideManualClick;
        __spoken.push(utterance.text);queueMicrotask(()=>{utterance.onstart?.();utterance.onend?.();});};
      __insideManualClick=true;
      document.querySelector('[data-segment-id=retryable-final] [data-v2-play]').click();
      __insideManualClick=false;
    }""")
    page.wait_for_function("__spoken.length === 2")
    assert page.evaluate("__spoken") == ["Retry me", "Retry me"]
    assert page.evaluate("__manualWasSynchronous") is True
    page.evaluate("speechSynthesis.speak=utterance=>{const fail=utterance&&utterance.onerror;queueMicrotask(()=>fail?.({error:'not-allowed'}));}")
    page.locator("[data-segment-id=retryable-final] [data-v2-play]").click()
    expect(page.locator("[data-v2-error]")).to_have_attribute("data-error-category", "TTS_PLAYBACK_STATE")


def test_tts_waits_for_voiceschanged_and_selects_matching_voice(page):
    voice_setup(page)
    page.evaluate("""() => {
      window.__voices=[];window.__selectedVoice='';
      window.SpeechSynthesisUtterance=class { constructor(text){this.text=text;this.lang='';this.voice=null;} };
      Object.defineProperty(speechSynthesis,'getVoices',{configurable:true,value:()=>__voices});
      speechSynthesis.cancel=()=>{};
      speechSynthesis.speak=utterance=>{__selectedVoice=utterance.voice?.name||'';
        queueMicrotask(()=>{utterance.onstart?.();utterance.onend?.();});};
      GroupV3TtsManager.configureForTests({voiceWaitMs:500,startTimeoutMs:500});
      GroupV3TtsManager.enqueue({key:'voices-ready',text:'Xin chào',language:'vi',automatic:true});
    }""")
    page.wait_for_timeout(30)
    assert page.evaluate("__selectedVoice") == ""
    assert page.evaluate("GroupV3TtsManager.state()") == "VOICE_LOADING"
    assert "không hỗ trợ" not in page.locator("[data-v2-error]").inner_text().lower()
    page.evaluate("""() => {
      window.__voices=[{name:'Vietnamese QA',lang:'vi-VN'}];
      speechSynthesis.dispatchEvent(new Event('voiceschanged'));
    }""")
    page.wait_for_function("__selectedVoice === 'Vietnamese QA'")


def test_processing_history_converges_and_sse_open_reconciles(page):
    voice_setup(page)
    calls = {"history":0}
    processing = {"id":"eventual-final","state":"PROCESSING","translated_text":None,"source_text":"Original",
        "created_at":"2026-09-06T00:00:01Z","speaker_membership_id":"m2",
        "display_language":"en","target_language":"en","author_view":False}
    final = dict(processing, state="FINAL", translated_text="Converged")
    def history(route):
        calls["history"] += 1
        route.fulfill(content_type="application/json", body=json.dumps({"segments":[processing if calls["history"] == 1 else final]}))
    page.route("**/translation/v2-history?*", history)
    page.evaluate("GroupV3TranslationController.loadHistory(document.querySelector('[data-group-translation-v2]'))")
    expect(page.locator("[data-segment-id=eventual-final]")).to_contain_text("Converged")
    before = calls["history"]
    page.evaluate("__eventSources[0].emit('open')")
    page.wait_for_function("() => window.GroupV3TranslationController && document.querySelector('[data-segment-id=eventual-final]')")
    page.wait_for_timeout(250)
    assert calls["history"] > before


def test_translation_event_during_submit_is_not_lost(page):
    voice_setup(page)
    calls = {"history": 0}
    item = {"id":"busy-event-final","state":"FINAL","translated_text":"Busy event retained",
        "source_text":"Submitted while event arrived","created_at":"2026-09-06T00:00:02Z",
        "speaker_membership_id":"m2","display_language":"zh-TW","target_language":"zh-TW",
        "author_view":False}
    page.route("**/translation/segments/text", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"segment":item})))
    def history(route):
        calls["history"] += 1
        route.fulfill(content_type="application/json", body=json.dumps({"segments":[item]}))
    page.route("**/translation/v2-history?*", history)
    page.locator("[data-v2-text]").fill("Submitted while event arrived")
    page.evaluate("""() => {
      document.querySelector('[data-v2-action=send]').click();
      window.dispatchEvent(new CustomEvent('group-v3:translation-segment', {detail:{id:'busy-event-final'}}));
    }""")
    expect(page.locator("[data-segment-id=busy-event-final]")).to_contain_text("Busy event retained")
    page.wait_for_function("() => document.querySelector('[data-group-translation-v2]').dataset.translationState !== 'PROCESSING'")
    page.wait_for_timeout(100)
    assert calls["history"] >= 2


def test_translation_device_settings_are_local_shared_and_permission_safe(page):
    boot(page, surface="chat-translation", connected=False)
    expect(page.locator(".communication-device-settings")).to_be_visible()
    assert page.evaluate("__mediaCounts.acquire") == 0
    page.locator("[data-change=device-pref-audio]").select_option("mic-qa")
    page.locator("[data-change=device-pref-video]").select_option("camera-qa")
    page.locator("[data-change=device-pref-output]").select_option("speaker-qa")
    assert page.evaluate("__mediaCounts.acquire") == 0
    assert page.evaluate("GroupV3DeviceManager.preferences()") == {
        "audioInput":"mic-qa", "videoInput":"camera-qa", "audioOutput":"speaker-qa"}
    page.locator("[data-action=test-microphone]").click()
    expect(page.locator(".communication-device-status")).to_contain_text("Mic hoạt động")
    assert page.evaluate("__mediaCounts.acquire") == 1
    page.evaluate("""() => {window.__spoken=[];speechSynthesis.cancel=()=>{};speechSynthesis.speak=u=>{
      __spoken.push(u.text);queueMicrotask(()=>{u.onstart?.();u.onend?.();});};}""")
    page.locator("[data-action=test-device-voice]").click()
    page.wait_for_function("__spoken.length === 1")
    expect(page.locator(".communication-device-status")).to_contain_text("Giọng đọc hoạt động")
    page.reload()
    expect(page.locator("[data-change=device-pref-audio]")).to_have_value("mic-qa")
    assert page.evaluate("__mediaCounts.acquire") == 0
    page.locator("[data-surface=radio]:visible").click()
    page.locator(".radio-ptt").click()
    page.wait_for_function("GroupV3Runtime.snapshot().media_connected")
    page.locator(".radio-ptt").click()
    page.wait_for_function("__mediaCounts.acquire === 1")
    assert page.evaluate("__lastAcquire.audioDeviceId") == "mic-qa"


def test_unsupported_output_selection_is_reported_as_os_managed(page):
    boot(page, surface="chat-translation", connected=False, output_supported=False)
    expect(page.locator(".device-output-managed")).to_contain_text("hệ điều hành")
    expect(page.locator("[data-change=device-pref-output]")).to_have_count(0)
    assert page.evaluate("__mediaCounts.acquire") == 0


def test_archive_manual_tts_failure_is_visible_instead_of_silent(page):
    boot(page, surface="chat-translation", connected=False)
    item = {"id":"archive-manual","runtime_kind":"video","state":"FINAL",
        "translated_text":"Visible archive speech","source_text":"Original",
        "created_at":"2026-09-06T00:00:03Z","speaker_membership_id":"m2",
        "speaker_display_name":"Trần An","display_language":"en","target_language":"en",
        "author_view":False,"projection":"recipient"}
    page.route("**/translation/v2-history?*", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"segments":[item]})))
    page.locator("[data-action=history-tab][data-tab=media]").click()
    expect(page.locator("[data-translation-archive] [data-v2-play]")).to_be_visible()
    page.evaluate("""() => {speechSynthesis.cancel=()=>{};speechSynthesis.speak=u=>{
      queueMicrotask(()=>u.onerror?.({error:'not-allowed'}));};}""")
    page.locator("[data-translation-archive] [data-v2-play]").click()
    expect(page.locator("[data-toast]")).to_have_class("toast is-visible")
    expect(page.locator("[data-toast]")).to_contain_text("phát giọng")


def test_historical_translate_is_on_demand_and_never_auto_speaks(page):
    boot(page, surface="chat-translation", connected=False)
    missing = {"id":"history-missing","runtime_kind":"video","state":"FAILED",
        "failure_code":"group_translation_variant_missing","translated_text":None,
        "source_text":"Nguồn lịch sử luôn hiển thị","source_language":"vi",
        "created_at":"2026-09-06T00:00:03Z","speaker_membership_id":"m2",
        "speaker_display_name":"Trần An","display_language":"zh-TW","target_language":"zh-TW",
        "author_view":False,"projection":"recipient","show_original_enabled":False}
    final = dict(missing, state="FINAL", failure_code=None, translated_text="歷史翻譯")
    page.route("**/translation/v2-history?*", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"segments":[missing]})))
    page.route("**/translation/segments/history-missing/variants/zh-TW/retry", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"segment":final})))
    page.locator("[data-action=history-tab][data-tab=media]").click()
    expect(page.locator("article[data-segment-id=history-missing]")).to_contain_text("Nguồn lịch sử luôn hiển thị")
    expect(page.locator("[data-action=history-translate]")).to_be_visible()
    page.locator("[data-action=toggle-auto-read]").click()
    page.wait_for_function("GroupV3Runtime.snapshot().auto_read")
    page.evaluate("""() => {window.__spoken=[];speechSynthesis.cancel=()=>{};speechSynthesis.speak=u=>{
      __spoken.push(u.text);queueMicrotask(()=>{u.onstart?.();u.onend?.();});};}""")
    page.locator("[data-action=history-translate]").click()
    expect(page.locator("article[data-segment-id=history-missing]")).to_contain_text("歷史翻譯")
    assert page.evaluate("__spoken") == []
    page.locator("[data-segment-id=history-missing] [data-v2-play]").click()
    page.wait_for_function("__spoken.length === 1")
    assert page.evaluate("__spoken") == ["歷史翻譯"]


def test_radio_final_remains_autoread_eligible_until_listen_media_connects(page):
    boot(page, surface="radio", connected=False)
    segment = {"id":"radio-remote-final","state":"FINAL","translated_text":"Radio translated",
        "source_text":"Radio source","created_at":"2026-09-06T00:00:01Z","speaker_membership_id":"m2",
        "display_language":"vi","target_language":"vi","author_view":False}
    burst = {"id":"remote-burst","state":"final","speaker_display_name":"Trần An",
        "started_at":"2026-09-06T00:00:01Z","segment":segment}
    page.route("**/radio/history?*", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"bursts":[burst]})))
    page.evaluate("""() => {
      GroupV3Runtime.updateProfile({auto_read_enabled:true});window.__spoken=[];
      speechSynthesis.cancel=()=>{};speechSynthesis.speak=u=>{if(u.text!=='\u200b')__spoken.push(u.text);queueMicrotask(()=>{u.onstart?.();u.onend?.();});};
    }""")
    page.evaluate("""() => window.dispatchEvent(new CustomEvent('group-v3:translation-segment',
      {detail:{type:'translation.segment.changed',resource_id:'radio-remote-final'}}))""")
    page.evaluate("segment => GroupV3TranslationController.readRadioHistory([segment])", segment)
    assert page.evaluate("__spoken") == []
    page.locator(".radio-ptt").click()
    page.wait_for_function("GroupV3Runtime.snapshot().media_connected && __spoken.length === 1")
    assert page.evaluate("__spoken") == ["Radio translated"]
    page.locator("[data-radio-burst=remote-burst] [data-v2-play]").click()
    page.wait_for_function("__spoken.length === 2")
    assert page.evaluate("__spoken") == ["Radio translated", "Radio translated"]


@pytest.mark.parametrize("width,height", [(1440,900),(390,844),(844,390)])
def test_member_picker_uses_available_height_and_keeps_action_visible(page, width, height):
    page.set_viewport_size({"width":width,"height":height})
    boot(page, surface="video", connected=False, participant_count=8, has_session=False)
    form = page.locator(".media-start-form")
    expect(form).to_be_visible()
    form_box = form.bounding_box()
    list_box = page.locator(".media-member-list").bounding_box()
    action_box = form.locator("button[type=submit]").bounding_box()
    if width <= 844:
        assert form_box["height"] >= (160 if height < 500 else 300)
    assert list_box["height"] >= (90 if height < 500 else 100)
    assert action_box["y"] + action_box["height"] <= min(height, form_box["y"] + form_box["height"] + 1)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("surface", ["call", "video"])
def test_incoming_ringtone_stops_for_every_non_incoming_runtime_state(page, surface):
    runtime = boot(
        page,
        surface=surface,
        connected=False,
        spaces=[
            {"id": "s1", "title": "Điều phối QA", "status": "active", "version": 1},
            {"id": "s0", "title": "Nhóm khác", "status": "active", "version": 1},
        ],
        session_status="ringing",
        self_invite_status="invited",
        initiated_by_membership_id="m2",
    )
    expect(page.locator(".incoming-stage")).to_be_visible()
    page.evaluate(
        """() => {
          const control = document.createElement('button');
          control.type = 'button';
          control.dataset.action = 'qa-noop';
          control.textContent = 'Arm';
          control.style.cssText = 'position:fixed;inset:8px auto auto 8px;z-index:10000';
          document.querySelector('#group-native-app').append(control);
        }"""
    )
    page.locator('[data-action="qa-noop"]').click()
    page.wait_for_function(
        """() => {
          const state = GroupV3IncomingRingtone.diagnostics();
          return state.key === 'r1' && state.armed && state.leader;
        }"""
    )
    page.evaluate(
        """() => {
          const ringback = window.GroupV3Ringback;
          window.__ringbackEvents = [];
          window.GroupV3Ringback = {
            start(key) { window.__ringbackEvents.push({type: 'start', key}); ringback.start(key); },
            stop() { window.__ringbackEvents.push({type: 'stop'}); ringback.stop(); },
            arm() { ringback.arm(); }
          };
        }"""
    )
    session = runtime["session"]
    participant = session["participants"][0]
    session["id"] = "r-replacement"
    page.evaluate(
        """() => window.__eventSources[0].emit('group-change', {
          space_id: 's1', type: 'media.session.changed'
        })"""
    )
    page.wait_for_function(
        """() => {
          const state = GroupV3IncomingRingtone.diagnostics();
          return state.key === 'r-replacement' && state.leader;
        }"""
    )

    terminal_cases = [
        ("accepted", "active", "joined", "m2"),
        ("rejected", "ringing", "rejected", "m2"),
        ("left", "ringing", "left", "m2"),
        ("cancelled", "cancelled", "invited", "m2"),
        ("expired", "expired", "invited", "m2"),
        ("missed", "missed", "invited", "m2"),
        ("outgoing-caller", "ringing", "joined", "m1"),
        ("ended", "ended", "invited", "m2"),
    ]
    for index, (label, status, invite_status, initiator) in enumerate(
        terminal_cases, start=1
    ):
        if index > 1:
            session["id"] = f"r{index}"
            session["status"] = "ringing"
            session["initiated_by_membership_id"] = "m2"
            participant["invite_status"] = "invited"
            page.evaluate(
                """() => window.__eventSources[0].emit('group-change', {
                  space_id: 's1', type: 'media.session.changed'
                })"""
            )
            page.wait_for_function(
                "expected => GroupV3IncomingRingtone.diagnostics().key === expected",
                arg=f"r{index}",
            )

        session["status"] = status
        session["initiated_by_membership_id"] = initiator
        participant["invite_status"] = invite_status
        page.evaluate(
            """() => window.__eventSources[0].emit('group-change', {
              space_id: 's1', type: 'media.session.changed'
            })"""
        )
        page.wait_for_function(
            "GroupV3IncomingRingtone.diagnostics().key === ''"
        )
        assert not page.evaluate(
            "GroupV3IncomingRingtone.diagnostics().leader"
        ), label
        if label == "outgoing-caller":
            assert page.evaluate(
                "expected => window.__ringbackEvents.some(event => "
                "event.type === 'start' && event.key === expected)",
                arg=session["id"],
            )

    session["id"] = "r-room-switch"
    session["status"] = "ringing"
    session["initiated_by_membership_id"] = "m2"
    participant["invite_status"] = "invited"
    page.evaluate(
        """() => window.__eventSources[0].emit('group-change', {
          space_id: 's1', type: 'media.session.changed'
        })"""
    )
    page.wait_for_function(
        "GroupV3IncomingRingtone.diagnostics().key === 'r-room-switch'"
    )
    page.set_viewport_size({"width": 1440, "height": 900})
    expect(page.locator(".context-rail")).to_be_visible()
    room_s0 = page.locator('.context-rail [data-action="select-space"][data-id="s0"]')
    expect(room_s0).to_be_visible()
    room_s0.click()
    page.wait_for_function(
        """() => GroupV3Runtime.snapshot().space_id === 's0'
          && GroupV3IncomingRingtone.diagnostics().key === ''
          && !GroupV3IncomingRingtone.diagnostics().leader"""
    )
    room_s1 = page.locator('.context-rail [data-action="select-space"][data-id="s1"]')
    expect(room_s1).to_be_visible()
    room_s1.click()
    page.wait_for_function(
        """() => GroupV3Runtime.snapshot().space_id === 's1'
          && GroupV3IncomingRingtone.diagnostics().key === 'r-room-switch'"""
    )
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
    page.wait_for_function(
        """() => GroupV3IncomingRingtone.diagnostics().key === ''
          && !GroupV3IncomingRingtone.diagnostics().leader"""
    )


def test_radio_runtime_never_starts_custom_incoming_ringtone(page):
    boot(page, surface="radio", connected=False)
    page.locator(".radio-ptt").click()
    page.wait_for_function("GroupV3Runtime.snapshot().media_connected")
    assert page.evaluate("GroupV3IncomingRingtone.diagnostics().key") == ""
    assert not page.evaluate("GroupV3IncomingRingtone.diagnostics().leader")


@pytest.mark.parametrize("surface", ["call", "video"])
def test_ringtone_multitab_has_one_audible_owner_and_stops_terminally(
    chromium_browser, surface
):
    ringtone_source = (
        ROOT / "app/static/group-v3/group_incoming_ringtone.js"
    ).read_text(encoding="utf-8")
    html = """<!doctype html>
<html><head><meta charset="utf-8">
<script>
window.__toneStarts = 0;
window.__qaRingtoneKey = '';
window.AudioContext = class {
  constructor() { this.state = 'running'; this.currentTime = 0; this.destination = {}; }
  resume() { this.state = 'running'; return Promise.resolve(); }
  createOscillator() {
    return {
      type: '', frequency: { value: 0 }, onended: null,
      connect(node) { return node; },
      disconnect() {},
      start() { window.__toneStarts += 1; },
      stop() { if (this.onended) this.onended(); }
    };
  }
  createGain() {
    return {
      gain: {
        setValueAtTime() {},
        exponentialRampToValueAtTime() {}
      },
      connect(node) { return node; },
      disconnect() {}
    };
  }
};
</script>
<script src="/group_incoming_ringtone.js" defer></script>
</head><body><button id="arm" type="button">Arm ringtone</button>
<script>
document.querySelector('#arm').addEventListener('click', () => {
  GroupV3IncomingRingtone.start(window.__qaRingtoneKey, { durationSeconds: 15 });
  GroupV3IncomingRingtone.arm();
});
</script></body></html>"""
    context = chromium_browser.new_context(service_workers="block")

    def fulfill(route):
        path = urlparse(route.request.url).path
        if path == "/group_incoming_ringtone.js":
            return route.fulfill(
                content_type="application/javascript", body=ringtone_source
            )
        return route.fulfill(content_type="text/html", body=html)

    context.route("http://127.0.0.1:8766/**", fulfill)
    errors = []
    try:
        pages = [context.new_page(), context.new_page()]
        for current in pages:
            current.on("pageerror", lambda error: errors.append(str(error)))
            current.goto("http://127.0.0.1:8766/")
            current.evaluate(
                "key => { window.__qaRingtoneKey = key; }",
                f"{surface}:session-qa",
            )
            current.locator("#arm").click()
        pages[0].wait_for_timeout(500)

        diagnostics = [
            current.evaluate("GroupV3IncomingRingtone.diagnostics()")
            for current in pages
        ]
        leaders = [index for index, item in enumerate(diagnostics) if item["leader"]]
        assert all(item["armed"] and item["visible"] for item in diagnostics), diagnostics
        assert len(leaders) == 1, diagnostics
        tone_counts = [current.evaluate("window.__toneStarts") for current in pages]
        assert tone_counts[leaders[0]] > 0, tone_counts
        assert tone_counts[1 - leaders[0]] == 0, tone_counts

        leader = pages[leaders[0]]
        survivor = pages[1 - leaders[0]]
        survivor_before = survivor.evaluate("window.__toneStarts")
        leader.close()
        survivor.wait_for_function(
            "GroupV3IncomingRingtone.diagnostics().leader === true"
        )
        survivor.wait_for_function(
            "before => window.__toneStarts > before", arg=survivor_before
        )

        survivor.evaluate("GroupV3IncomingRingtone.stop()")
        terminal = survivor.evaluate("GroupV3IncomingRingtone.diagnostics()")
        assert terminal["key"] == ""
        assert terminal["leader"] is False
        stopped_count = survivor.evaluate("window.__toneStarts")
        survivor.wait_for_timeout(1800)
        assert survivor.evaluate("window.__toneStarts") == stopped_count
        assert not errors, errors
    finally:
        context.close()


@pytest.mark.parametrize("width,height",[(390,844),(844,390)])
def test_webkit_workspace_and_visual_viewport(webkit_browser,tmp_path,width,height):
    context=webkit_browser.new_context(viewport={"width":width,"height":height},is_mobile=True,has_touch=True)
    page=context.new_page()
    boot(page,connected=False)
    page.locator('[data-workspace-action=translation-plus]').click()
    expect(page.locator(".translation-dock")).to_have_attribute("data-translation-mode","HALF")
    page.locator('[data-workspace-action=translation-plus]').click()
    expect(page.locator(".translation-dock")).to_have_attribute("data-translation-mode","FULL")
    page.locator('[data-workspace-action=translation-minus]').click()
    page.locator('[data-workspace-action=translation-minus]').click()
    g=geometry(page)
    assert g[".surface-content"]["height"] == height - 8, g
    assert g[".translation-dock"]["bottom"] == height, g
    page.screenshot(path=str(tmp_path / f"webkit-{width}x{height}.png"))
    context.close()
