# TB-GROUP-COLLAB-20260906-002-R1 — PR #36 Mobile Radio persistent-room corrective

Status: **OWNER-QA FAILED / CORRECTIVE PLAN LOCKED / NO MERGE / NO DEPLOY**
Planner: ChatGPT GPT-5.6 Sol
Repository: `Panjiaphu/AI-COMMUNICATION-Timeblock`
PR: `#36`
Branch: `docs/group-chat-shared-variant-speaker-cost-20260906`
Parent task: `docs/qa/TB-GROUP-COLLAB-20260906-002-PR36-EXECUTION.md`

## 0. Canonical workflow and model gate

Read and obey, in order:

1. `AGENTS.md`
2. `docs/engineering/CHATGPT_CODEX_PLANNER_EXECUTOR_STANDARD.md` (v1.3.1)
3. `docs/engineering/LEGACY_WORKFLOW_BLOCKLIST.md`
4. this corrective task
5. only the relevant current source/tests

Current repository contract requires **fresh Codex GPT-5.6 Sol High** for a high-risk write executor. The owner requested GPT-5.6 Luna Deep for this corrective, but this task changes LiveKit permission/floor/microphone lifecycle and is **not** a low-risk mechanical task. Therefore:

```text
OWNER_REQUESTED_LUNA=YES
LUNA_READ_ONLY_AUDIT_ALLOWED=YES
LUNA_WRITE_EXECUTOR_ALLOWED=NO
WRITE_EXECUTOR_REQUIRED_BY_REPO_CONTRACT=GPT-5.6 Sol High
```

Do not silently override `AGENTS.md`. If the active executor is Luna, it may perform a read-only audit and return a bounded handoff, but it must not modify production/test source on this task tree.

## 1. Exact lineage

Owner-deployed/QA pair for PR #36 before this corrective:

```text
TIMEBLOCK_DEPLOYED_QA_SHA=ff5df2de30dac10d357894e67ce1187af364ed88
GUILUA_FAILED_OWNER_QA_SHA=b1a3926c46019ca489a70367e804db9c4086b28f
GUILUA_PR=36
GUILUA_PR36_BASE_MAIN=1dd41308b4fda33797b3de3b09c5bc13efd0b720
```

PR #36 core automated/UI QA previously passed, but owner physical iPhone QA found a Radio blocker. Continue on the **same PR #36 branch**. Never restart from `main`. Never drop migration `20260907_0024` or the already-tested PR #36 Group Chat/notification work.

Before any write, verify:

```text
CURRENT_MAIN_SHA=
CURRENT_PR36_HEAD_SHA=
FAILED_OWNER_QA_SHA=b1a3926c46019ca489a70367e804db9c4086b28f
PLAN_SHA=<this task commit>
LINEAGE_RELATION=PLAN_SHA descends from failed owner-QA candidate
```

If the branch has moved and the failed candidate is no longer an ancestor, STOP and report `BLOCKED_LINEAGE`.

## 2. Owner physical QA evidence

Confirmed PASS:

```text
DESKTOP_UI=PASS
MOBILE_UI=PASS
DESKTOP_PWA_UI=PASS
MOBILE_PWA_UI=PASS
GROUP_CHAT_CORE=PASS
GROUP_NOTIFICATION_CORE=PASS
CALL_UI=PASS
VIDEO_UI=PASS
RADIO_LAYOUT=PASS
RAW_DESKTOP_TO_MOBILE_BEFORE_LOCAL_PTT=PASS
```

Confirmed FAIL sequence on iPhone/mobile PWA:

```text
1. Mobile is idle in Radio and hears desktop raw LiveKit voice in realtime.
2. Mobile taps PTT / Start talking.
3. iOS asks for microphone permission and shows the orange microphone indicator after Allow.
4. Mobile raw voice reaches desktop.
5. Mobile stops PTT.
6. Desktop speaks again.
7. Mobile is forced into remote-audio recovery / must tap "Bật âm thanh cuộc gọi" again.
```

The first microphone permission request is allowed/expected. The defect is repeated loss of remote playback readiness after local PTT.

## 3. Confirmed root cause in current source

Current Radio mode switching requests separate `listen` and `talk` grants and reconnects media:

```text
connectRadio("listen")
-> PTT
-> floor acquire
-> connectRadio("talk")
-> local recording/publish
-> floor stop
-> disconnectMedia(false)
-> connectRadio("listen")
```

Current `GroupV3DeviceManager.acquire()` also stops any existing `activeStream` before a new `getUserMedia()` request.

This destroys the same-session playback/microphone continuity that mobile Safari/PWA needs.

Corrective target:

```text
ONE RADIO SESSION
ONE PERSISTENT LIVEKIT ROOM CONNECTION
ONE OPTIONAL RETAINED MIC TRACK PER LIVE RADIO SESSION
ZERO ROOM RECONNECTS PER PTT
SERVER-AUTHORITATIVE FLOOR <-> LIVEKIT CANPUBLISH PERMISSION
```

## 4. Product UX — three explicit mobile controls

Add a narrowly-scoped Radio audio control block. Do not redesign the existing Radio layout.

Required controls:

```text
[ ] Mic sẵn sàng trong phiên
    Keeps one microphone capture track ready inside the current Radio session.
    It MUST NOT transmit audio without floor ownership.

[ ] Nghe giọng thật realtime
    Direct user gesture that unlocks raw LiveKit audio playback for the current runtime.

[ ] Tự đọc bản dịch realtime
    Direct user gesture that unlocks local TTS and auto-reads new FINAL translations only.
```

Semantics:

```text
MIC_READY_PREFERENCE != MIC_PERMISSION_GRANTED
RAW_LISTEN_PREFERENCE != ROOM_CAN_PLAY_AUDIO_RUNTIME_STATE
AUTO_READ_PREFERENCE != TTS_RUNTIME_UNLOCKED
```

Do not persist browser permission/unlocked runtime state as permanent truth.

Recommended mobile defaults:

```text
MIC_READY=OFF until explicit user tap
RAW_LISTEN_PREFERENCE=ON, but runtime may still require one tap
AUTO_READ=existing user preference
```

## 5. Persistent LiveKit Radio architecture

### 5.1 Join

Join the Radio room once with:

```text
canSubscribe=true
canPublish=false
canPublishSources=[]
```

Keep that Room instance for the life of the Radio session unless a **real transport/network/session lifecycle loss** requires reconnect.

### 5.2 Raw listen activation

The `Nghe giọng thật realtime` control must call LiveKit `room.startAudio()` directly in the user's click/tap handler. Reuse `GroupMediaPresentation.resumeAudio()` for attached remote tracks.

Forbidden:

```text
click -> await API/fetch -> room.startAudio()
```

Required:

```text
click/tap -> room.startAudio() immediately
              + resume attached remote audio
```

When `Room.canPlaybackAudio` later becomes false after a true browser/runtime lifecycle transition, mark runtime-ready false and show one explicit recovery control. Do not fake a click.

### 5.3 Mic ready

When user enables `Mic sẵn sàng trong phiên`:

```text
explicit user tap
-> getUserMedia(audio) once for the live Radio session
-> retain exactly one live microphone track when possible
-> keep it untransmitted when no floor is held
```

Do not call `getUserMedia()` on Radio page load.

Do not stop/reacquire this retained track after every PTT.

Stop the retained microphone track on:

```text
user disables Mic Ready
leave Radio
Radio session end
logout/runtime teardown
membership/device loss requiring privacy cleanup
page termination
```

If the track ends because the device disappears, reacquire only from a later explicit user gesture; do not silently loop permission prompts.

### 5.4 PTT start

Required ordering:

```text
explicit PTT tap
-> ensure Mic Ready track exists (same gesture if needed)
-> acquire authoritative Redis/Valkey floor
-> server promotes current LiveKit participant:
     canSubscribe=true
     canPublish=true
     canPublishSources=[microphone]
-> wait for permission state/acknowledgement needed for safe publish
-> publish/enable SAME retained microphone track
-> start Radio recorder from SAME live track
-> heartbeat floor
```

Never create a second microphone owner.

### 5.5 PTT stop

Required ordering is safety-critical:

```text
stop/finalize MediaRecorder input first enough to preserve the tail of speech
-> stop/release floor server-side
-> unpublish/mute the microphone track
-> server demotes participant:
     canPublish=false
     canSubscribe=true
-> KEEP SAME ROOM CONNECTED
-> keep retained local mic track only if Mic Ready remains ON
-> continue receiving remote raw audio immediately
-> run STT/translation finalization detached from floor ownership
```

Do not reconnect into a new `listen` Room after each PTT.

### 5.6 Floor timeout / device lost / leave

All abnormal terminal paths must converge on fail-closed media permission:

```text
floor timeout -> canPublish=false
heartbeat max burst -> canPublish=false
device lost -> canPublish=false
leave -> canPublish=false and disconnect Room
end-for-all -> canPublish=false and disconnect Room
page teardown -> release floor best-effort + stop mic + disconnect
```

No stale LiveKit publisher may survive after the canonical floor is gone.

## 6. LiveKit Cloud permission contract

Use the official LiveKit server `UpdateParticipant` permission mechanism or the safest current official server API integration available in this repository.

Required server operation:

```text
NO FLOOR:
  canSubscribe=true
  canPublish=false

FLOOR OWNER:
  canSubscribe=true
  canPublish=true
  canPublishSources=[microphone]
```

Do not rely on client-only `track.enabled` as the security boundary.

LiveKit Cloud token behavior must be accounted for:

- permission updates revoke outdated access tokens;
- connected clients receive refreshed tokens automatically;
- `ParticipantPermissionChanged` is emitted;
- revoking `CanPublish` automatically unpublishes published tracks.

Therefore test a **real reconnect after permission changes**. Do not keep using a stale cached join token for a later transport reconnect.

Do not reconnect merely because permissions changed.

## 7. TTS / translation interlock

The owner wants raw realtime voice and translated voice available independently.

When `Tự đọc bản dịch realtime` is enabled:

```text
user gesture -> GroupV3TtsManager.unlock()
new FINAL translation -> local TTS queue
history/bootstrap -> NEVER auto-read
```

Critical interlock:

```text
LOCAL FLOOR / LOCAL PTT ACTIVE
-> PAUSE/CANCEL CURRENT AUTO TTS AS NEEDED
-> QUEUE bounded new FINAL TTS

LOCAL FLOOR RELEASED
-> RESUME queued TTS
```

Prevent local speaker output from being re-captured into local mic/STT and causing echo/translation loops.

Manual historical playback remains user-triggered/local only.

## 8. Files — required audit/change scope

### Expected production write set

Audit first; modify only when evidence requires it:

```text
app/group_v3/media.py
app/group_v3/radio_service.py
app/group_v3/radio_router.py

app/static/group-v3/group_v3_app.js
app/static/group-v3/group_device_manager.js
app/static/group-v3/group_radio_ui.js
app/static/group-v3/group_tts_manager.js
app/static/group-v3/group_v3_i18n.js
app/static/group-v3/group_v3_runtime.css
app/templates/group_communication_v3.html
```

### Audit-only by default

```text
app/group_v3/radio_floor.py
app/group_v3/radio_schemas.py
app/static/group-v3/group_radio_recording.js
app/static/group-v3/group_media_presentation.js
requirements.txt
```

Only change an audit-only file if the exact current contract requires it. If adding a new backend LiveKit server dependency is truly required, explain why the existing `httpx`/provider boundary cannot safely implement the official operation before changing `requirements.txt`.

### Protected / no-write scope

```text
Timeblock repository: NO CHANGE
PR36 Group Chat shared translation architecture: NO CHANGE
PR36 Group notifications architecture: NO CHANGE
Call/Video layout and lifecycle: NO CHANGE except shared helper compatibility required to avoid regression
Direct 1:1: NO CHANGE
Cloudflare provider / PR37: NO WORK
Alembic schema: NO NEW MIGRATION
```

## 9. UI freeze

Already owner-QA-passed Group UI remains frozen.

Allowed UI change:

- one compact Radio audio controls block;
- states for Mic Ready / Raw Listen / Auto Read;
- narrowly scoped CSS/i18n;
- existing audio-blocked recovery may be reworded/merged with the Raw Listen control.

Forbidden:

```text
redesign/reposition Group nav
redesign Radio timeline
change PTT dock geometry
change Call/Video layout
change Translation dock layout
change mobile safe-area contract
production z-index hacks for tests
```

Must pass 390x844 and 390x667 with PTT/Leave controls visible and no horizontal overflow.

## 10. Failure modes that MUST be covered

```text
01 floor granted but canPublish update fails -> no mic publish
02 floor acquisition fails after Mic Ready -> no mic publish
03 client publish fails after floor grant -> release floor + demote
04 floor stop succeeds but demote fails -> retry/fail closed; no stale publish
05 max-burst timeout -> demote canPublish
06 device lost -> demote + stop retained track as privacy cleanup
07 second PTT reuses dead/disabled track -> detect and require explicit reacquire
08 MediaRecorder starts on muted/disabled track -> reject before talking state
09 recorder tail truncated by early unpublish -> ordering test
10 TTS plays into active local mic -> floor/TTS interlock
11 room.startAudio called outside direct gesture -> iOS playback remains blocked
12 saved Raw Listen preference says ON but runtime canPlaybackAudio=false -> show activation needed
13 iOS PWA cold start asks mic again -> classify as browser lifecycle, do not fake persistence
14 orange mic indicator remains while Mic Ready ON -> disclose, stop on user OFF/leave
15 Bluetooth/AirPods input disappears -> retained track ended path
16 background/foreground suspends Room -> real reconnect only, not PTT reconnect
17 reconnect after UpdateParticipant uses stale token -> must recover with refreshed/current grant
18 remote track duplicate attach after reconnect -> no echo/double playback
19 multi-tab same user microphone contention -> no silent second capture owner
20 floor TTL lost in Redis while LiveKit still publishable -> reconcile/demote
21 Radio leave/end leaves mic indicator on -> privacy failure
22 three new controls overflow 390x667 -> UI failure
23 TTS queue grows unbounded during long local talk -> bounded/coalesced queue
24 GroupSpace switch plays stale queued TTS -> space/session ownership check
25 generic media helper refactor breaks Call/Video -> regression failure
26 Group Chat/notification files drift -> scope failure
```

## 11. Required tests to write/update before running QA

At minimum cover:

```text
tests/browser/test_group_corrective.py
tests/test_group_radio_floor_v3.py
tests/test_group_radio_v3_closure.py
tests/test_group_r1_closure.py
tests/test_group_v3_native.py
tests/test_group_v3_prejoin_contract.py
tests/test_render_contract_gate.py
```

A focused new browser file is allowed if it is cleaner:

```text
tests/browser/test_group_radio_mobile_audio_activation.py
```

Test harness must prove actual state transitions; do not edit production layout solely to make test controls clickable.

## 12. Acceptance contract

### Transport / room

```text
RADIO_ROOM_CONNECTIONS_PER_LIVE_SESSION=1
ROOM_RECONNECTS_PER_PTT=0
ROOM_ID_BEFORE_PTT==ROOM_ID_AFTER_PTT
PTT_1=PASS
PTT_2=PASS
PTT_10=PASS
```

A network-loss reconnect may increment room connections, but a PTT action may not.

### Microphone

```text
MIC_PERMISSION_PROMPTS_WITHIN_ONE_LIVE_RADIO_SESSION<=1 target
MIC_TRACK_REUSED_WHILE_MIC_READY=PASS
NO_FLOOR_REMOTE_MIC_AUDIO=0
FLOOR_OWNER_RAW_AUDIO=PASS
LEAVE_RADIO_STOPS_MIC_CAPTURE=PASS
MIC_READY_OFF_STOPS_MIC_CAPTURE=PASS
```

The executor must not claim iOS can guarantee permission persistence across PWA cold starts.

### Raw listen

```text
MOBILE_IDLE_HEARS_DESKTOP_RAW=PASS
RAW_LISTEN_DIRECT_USER_GESTURE=PASS
DESKTOP_REPLY_AFTER_MOBILE_PTT_HEARD_IMMEDIATELY=PASS
REMOTE_AUDIO_UNLOCK_PROMPTS_AFTER_PTT=0
```

### Translation/TTS

```text
NEW_FINAL_TRANSLATION_VISIBLE=PASS
AUTO_READ_RUNTIME_UNLOCK_DIRECT_GESTURE=PASS
AUTO_READ_NEW_FINAL=PASS
HISTORY_AUTO_READ=NO
TTS_PAUSED_OR_QUEUED_WHILE_LOCAL_FLOOR=PASS
NO_LOCAL_TTS_TO_STT_LOOP=PASS
```

### Security / floor

```text
NO_FLOOR_CAN_PUBLISH=false
FLOOR_OWNER_CAN_PUBLISH=true
CAN_PUBLISH_SOURCES=MICROPHONE_ONLY
FLOOR_TIMEOUT_DEMOTES=PASS
DEVICE_LOST_DEMOTES=PASS
LEAVE_DEMOTES=PASS
```

### Regression / boundaries

```text
CALL_REGRESSION=PASS
VIDEO_REGRESSION=PASS
GROUP_CHAT_REGRESSION=PASS
GROUP_NOTIFICATION_REGRESSION=PASS
RADIO_NOTIFICATION_REGRESSION=PASS
DIRECT_1_1_CHANGED=NO
TIMEBLOCK_CODE_CHANGED=NO
DATABASE_CHANGED=NO
NEW_MIGRATION=NO
PR37_STARTED=NO
```

### UI

```text
DESKTOP_EXISTING_LAYOUT_CHANGED=NO
MOBILE_EXISTING_LAYOUT_CHANGED=NO
PWA_SHELL_CHANGED=NO
MOBILE_390X844=PASS
MOBILE_390X667=PASS
PTT_VISIBLE_WITH_AUDIO_CONTROLS=PASS
NO_HORIZONTAL_OVERFLOW=PASS
```

## 13. Execution phases — NO intermediate QA

```text
PHASE 0 — verify exact lineage/model/tool contract; NO QA
PHASE 1 — inspect current Radio/LiveKit source and tests only; NO QA
PHASE 2 — implement backend persistent-permission/floor integration; NO QA
PHASE 3 — implement persistent Room + retained mic lifecycle; NO QA
PHASE 4 — add three mobile audio controls + TTS interlock; NO QA
PHASE 5 — write/update all regression test source; DO NOT RUN
PHASE 6 — static completeness/protected-boundary review; NO QA
PHASE 7 — freeze exact local candidate commit
PHASE 8 — ONE final local QA gate against frozen candidate
PHASE 9 — push exact tested candidate to SAME PR #36
PHASE 10 — verify remote head == tested SHA; report DEPLOY_TEST_SHA and STOP
```

If final QA finds a defect, fix it in an additional commit and rerun only the affected final gate plus any directly coupled regression gate. Never amend/rewrite the already-tested commit.

## 14. Final QA gate

Required deterministic gate:

```text
Python focused Radio/floor/media tests
JS syntax for every changed Group script
browser deterministic Radio PTT 1/2/10 cycles
390x844
390x667
Call regression
Video regression
Group Chat regression
Group notification regression
Render contract
source lock
git diff --check
Alembic heads unchanged at 20260907_0024
```

Browser automation cannot prove actual iPhone permission persistence or physical audio routing. Final report must leave:

```text
OWNER_MANUAL_IPHONE_RADIO_QA=PENDING
OWNER_MANUAL_PWA_MIC_PERMISSION_QA=PENDING
OWNER_MANUAL_BLUETOOTH_QA=PENDING unless physically tested by owner
```

## 15. Tool scope

```text
REQUIRED_PLUGINS=GitHub
OPTIONAL_PLUGINS=Browser only if available for final rendered QA; otherwise repository Playwright with reason recorded
RENDER=READ-ONLY only if runtime evidence is necessary; NEVER deploy
TIMEBLOCK_WRITE=FORBIDDEN
```

Do not use GitHub Actions as iterative QA.

## 16. Stop conditions

STOP and report BLOCKED if any of these is true:

```text
branch/head lineage cannot preserve b1a3926c46019ca489a70367e804db9c4086b28f
LiveKit server permission update cannot be implemented without an unapproved architecture rewrite
persistent Room requires changing Direct 1:1 ownership
corrective requires Timeblock production code changes
corrective requires a database migration
Call/Video must be materially rewritten
executor is Luna and intends to write despite the current model contract
```

## 17. Final report schema

Return exactly these fields plus brief test counts:

```text
STATUS=READY_FOR_OWNER_DEPLOY_QA|BLOCKED
TASK_ID=TB-GROUP-COLLAB-20260906-002-R1
PLAN_SHA=
FAILED_OWNER_QA_SHA=b1a3926c46019ca489a70367e804db9c4086b28f
TIMEBLOCK_PAIRED_SHA=ff5df2de30dac10d357894e67ce1187af364ed88
PR_NUMBER=36
BRANCH=docs/group-chat-shared-variant-speaker-cost-20260906
EXECUTOR_MODEL=

CANDIDATE_SHA=
TESTED_COMMIT_SHA=
REMOTE_PR_HEAD_SHA=
DEPLOY_TEST_SHA=

PERSISTENT_RADIO_ROOM=
ROOM_RECONNECTS_PER_PTT=
MIC_READY_TRACK_REUSE=
RAW_LISTEN_USER_ACTIVATION=
AUTO_READ_USER_ACTIVATION=
TTS_LOCAL_FLOOR_INTERLOCK=
LIVEKIT_PERMISSION_PROMOTE_DEMOTE=
NETWORK_RECONNECT_AFTER_PERMISSION_CHANGE=

PTT_1=
PTT_2=
PTT_10=
DESKTOP_TO_MOBILE_RAW=
MOBILE_TO_DESKTOP_RAW=
DESKTOP_REPLY_AFTER_MOBILE_PTT=

FLOOR_TIMEOUT_DEMOTE=
DEVICE_LOST_DEMOTE=
LEAVE_RELEASES_MIC=

CALL_REGRESSION=
VIDEO_REGRESSION=
GROUP_CHAT_REGRESSION=
GROUP_NOTIFICATION_REGRESSION=

MOBILE_390X844=
MOBILE_390X667=
NO_HORIZONTAL_OVERFLOW=

TIMEBLOCK_CODE_CHANGED=NO
DIRECT_1_1_CHANGED=NO
DATABASE_CHANGED=NO
NEW_MIGRATION=NO
PR37_STARTED=NO
MERGED=NO
DEPLOYED=NO

OWNER_MANUAL_IPHONE_RADIO_QA=PENDING
OWNER_MANUAL_PWA_MIC_PERMISSION_QA=PENDING
READY_FOR_OWNER_DEPLOY_QA=YES|NO
```

If READY, provide exactly one new Guilua `DEPLOY_TEST_SHA` paired with unchanged Timeblock SHA `ff5df2de30dac10d357894e67ce1187af364ed88`, then STOP.