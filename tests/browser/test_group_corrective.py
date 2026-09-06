"""Actual Group template/scripts, deterministic API + media boundaries.

These checks are browser integration, not physical-device/LiveKit cloud proof.
Run once after source freeze: BROWSER_QA_ENABLED=1 pytest this-file.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from jinja2 import Environment

if os.getenv("BROWSER_QA_ENABLED") != "1":
    pytest.skip("Explicit final browser QA gate", allow_module_level=True)
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "app/static/group-v3"

DEVICE = """
window.__mediaCounts={acquire:0,publish:0,rooms:0,attach:0};
window.__devicePrefs=JSON.parse(localStorage.getItem('qa-device-prefs')||'{}');
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
 RoomEvent:{TrackSubscribed:'sub',TrackUnsubscribed:'unsub',Disconnected:'disconnected',ActiveSpeakersChanged:'speakers'},
 Track:{Source:{Camera:'camera',Microphone:'microphone'}},
 Room:class {
  constructor(){__mediaCounts.rooms++;this.events={};this.remoteParticipants=new Map();
    this.localParticipant={publishTrack:async()=>{__mediaCounts.publish++;}};}
  on(k,f){this.events[k]=f;return this;}
  async connect(){const stream=__makeStream();const track={
    kind:'video',sid:'remote-video-1',mediaStreamTrack:stream.getVideoTracks()[0],
    attach(){__mediaCounts.attach++;const v=document.createElement('video');v.srcObject=stream;v.muted=true;this.el=v;return v;},
    detach(){return this.el?[this.el]:[];}
   };this.remoteParticipants.set('guest',{identity:'guest',trackPublications:new Map([['v',{track}]])});
   this.events.sub?.(track,{}, {identity:'guest'});}
  removeAllListeners(){this.events={};}disconnect(){}
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
         output_supported=True):
    members = [dict(id="m1", principal_type="member", principal_id="42", principal_user_id="42",
        display_name="Nguyễn Minh", role="owner", status="active"),
        dict(id="m2", principal_type="member", principal_id="84", principal_user_id="84",
        display_name="Trần An", role="member", status="active")]
    people = [dict(id="p1", membership_id="m1", livekit_identity="owner", display_name="Nguyễn Minh", invite_status="joined", media_connected=True),
        dict(id="p2", membership_id="m2", livekit_identity="guest", display_name="Trần An", invite_status="joined", media_connected=True)]
    for index in range(2, participant_count):
        members.append(dict(id=f"m{index+1}", principal_type="member", principal_id=str(100+index), principal_user_id=str(100+index),
            display_name=f"QA {index}", role="member", status="active"))
        people.append(dict(id=f"p{index+1}", membership_id=f"m{index+1}", livekit_identity=f"guest{index}", display_name=f"QA {index}", invite_status="joined", media_connected=True))
    radio_people = [dict(p, status="joined", joined_at="2026-09-05T07:00:00Z") for p in people]
    radio_session = dict(id="r1", title="QA Radio", status="ready", participants=radio_people)
    radio_history = []
    radio_events = []
    session = dict(id="r1", media_kind="video", title="QA Video", status="active", participants=people)
    profile = dict(spoken_language="vi", preferred_output_language="zh-TW", auto_translate_enabled=False, auto_read_enabled=False)
    template = (ROOT / "app/templates/group_communication_v3.html").read_text(encoding="utf-8")
    # The external media SDK is the only replaced script. All Group scripts/CSS
    # and their production load order are unchanged.
    import re
    template = re.sub(r'<script src="https://cdn.jsdelivr.net[^<]+</script>', "", template)
    html = Environment().from_string(template).render(locale=locale, runtime_config={"locale":locale, "initial_surface":surface})
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
        if path.startswith("/group/"):
            return route.fulfill(content_type="text/html", body=html)
        payload = {}
        if path == "/api/group/session":
            payload = dict(principal=dict(type="member", id="42", user_id="42", locale=locale), group_authorized=True, direct_available=False)
        elif path == "/api/group/spaces":
            payload = {"spaces":[dict(id="s1",title="Điều phối QA",status="active",version=1)]}
        elif path.endswith("/memberships"): payload={"memberships":members}
        elif path.endswith("/translation/profile"):
            if route.request.method == "PUT": profile.update(route.request.post_data_json)
            payload={"profile":profile}
        elif path.endswith("/translation/consent"): payload={"consent":{"status":"granted"}}
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
        elif path.endswith("/sessions"): payload={"sessions":[session] if has_session else []}
        elif path.endswith("/radio/sessions/r1"): payload={"session":radio_session,"floor":None}
        elif path.endswith("/radio/sessions/r1/join"): payload={"session":session}
        elif path.endswith("/connection-state"): payload={"session":session}
        elif path.endswith("/media-grant"):
            payload={"grant":{"provider":"livekit-cloud","url":"wss://fixture.invalid","token":"fixture-only","participant_identity":"owner","media_kind":"audio" if "/radio/" in path else "video"}}
        route.fulfill(content_type="application/json", body=json.dumps(payload))
    page.route("**/*", handle)
    page.goto("http://127.0.0.1:8765/group/" + surface)
    expect(page.locator(".native-app")).to_be_visible()
    if connected:
        page.locator('.call-control-dock [data-action="connect-media"]').click()
        page.locator('[data-action="prepare-prejoin"]').click()
        page.locator('[data-action="confirm-prejoin"]').click()
        page.wait_for_function("GroupV3Runtime.snapshot().media_connected")
        expect(page.locator(".local-media")).to_have_count(1)
        expect(page.locator(".remote-media")).to_have_count(1)
        page.wait_for_function("document.querySelector('.remote-media').videoWidth > 0")


def geometry(page):
    return page.evaluate("""() => Object.fromEntries(
      ['.native-mobile','.native-main','.surface-content','.video-call-layout','.video-stage','.video-grid',
       '.call-control-dock','.translation-dock','.translation-dock__bar','.translation-dock__body','.translation-safety-layer']
      .map(s=>{let n=document.querySelector(s);if(!n)return [s,null];let r=n.getBoundingClientRect(),c=getComputedStyle(n);
      return [s,{x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,rows:c.gridTemplateRows,
        columns:c.gridTemplateColumns,padding:c.padding,minHeight:c.minHeight,display:c.display}]}))""")


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


def voice_setup(page, mime="audio/mp4"):
    boot(page)
    page.evaluate("(mime)=>window.__testMime=mime", mime)
    page.evaluate("() => {" + RECORDER + "}")
    page.locator('[data-workspace-action="translation-plus"]').click()
    return page.locator('[data-v2-action="record"]')


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
    page.evaluate("GroupV3TranslationController.loadHistory(document.querySelector('[data-group-translation-v2]'))")
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
    expect(page.locator("[data-v2-error]")).to_have_attribute("data-error-category", "TTS_ERROR")


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
    expect(page.locator("[data-segment-id=history-missing]")).to_contain_text("Nguồn lịch sử luôn hiển thị")
    expect(page.locator("[data-action=history-translate]")).to_be_visible()
    page.locator("[data-action=toggle-auto-read]").click()
    page.wait_for_function("GroupV3Runtime.snapshot().auto_read")
    page.evaluate("""() => {window.__spoken=[];speechSynthesis.cancel=()=>{};speechSynthesis.speak=u=>{
      __spoken.push(u.text);queueMicrotask(()=>{u.onstart?.();u.onend?.();});};}""")
    page.locator("[data-action=history-translate]").click()
    expect(page.locator("[data-segment-id=history-missing]")).to_contain_text("歷史翻譯")
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
      speechSynthesis.cancel=()=>{};speechSynthesis.speak=u=>{__spoken.push(u.text);queueMicrotask(()=>{u.onstart?.();u.onend?.();});};
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
    assert form_box["height"] >= (160 if height < 500 else 300)
    assert list_box["height"] >= (90 if height < 500 else 100)
    assert action_box["y"] + action_box["height"] <= min(height, form_box["y"] + form_box["height"] + 1)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


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
