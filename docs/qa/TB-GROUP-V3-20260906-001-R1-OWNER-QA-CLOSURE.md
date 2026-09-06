# TB-GROUP-V3-20260906-001-R1 — Owner QA Closure

## Status

- Repository: `Panjiaphu/AI-COMMUNICATION-Timeblock`
- Pull request: `#35`
- Owner-tested candidate before this task: `341893523b6903b168021847764b10d43907396d`
- Scope: corrective closure only
- Next product/update phase: **BLOCKED until owner QA PASS**
- Main merge: **NOT ALLOWED before owner QA PASS**
- Render deploy by executor: **NOT ALLOWED**

## Mission

Close all remaining owner-QA failures for Group Call, Group Video, Radio/PTT and Group Translation on the existing PR #35 lineage. Do not start a new feature/update stream. The next update is blocked until the owner deploys the final frozen candidate and reports QA PASS.

## Architecture lock

1. Canonical `GroupSpace` remains the single group-space/room source of truth.
2. Do not create a second room API, second room model or room database.
3. Direct 1:1 ownership/runtime remains unchanged.
4. Group raw media and translated speech are separate pipelines:

   `MIC -> LiveKit raw media -> remote listener`

   `MIC -> Group Translation -> STT -> translate -> optional FINAL TTS`

5. Translation TTS must never hide or replace broken raw LiveKit audio.
6. Call Translation must reuse the existing Group Translation V2 runtime.
7. Call Translation must reuse/clone/tap the Group-owned local audio track. A healthy active Call must not trigger a second `getUserMedia()` microphone owner.
8. Default expectations:

   - `DB_MIGRATION_REQUIRED=NO`
   - `NEW_ROOM_API=NO`
   - `NEW_CALL_TRANSLATION_BACKEND=NO`
   - `LIVEKIT_ARCHITECTURE_REWRITE=NO`
   - `DIRECT_1_1_CODE_CHANGED=NO`

Backend media/session code may change only when the implementation proves an existing contract is insufficient or non-idempotent.

---

## Owner-QA blockers

### P0-1 — Video asynchronous join race

Observed:

- Mobile enters Video first and waits.
- Desktop later presses Join and cannot reliably connect.
- When both devices press Join near-simultaneously, both can connect.

No Group media room may require simultaneous Join.

Trace:

- `session.status`
- participant `invite_status`
- participant `connection_status`
- `mediaGeneration`
- `mediaActionInFlight`
- prejoin/readiness state
- `localStream`
- `POST /join`
- connection-state request
- `POST /media-grant`
- LiveKit `Room.connect`
- local track publish
- `TrackSubscribed`
- SSE `group-change`
- `queueGroupEventRefresh`
- `loadSpaces`
- `loadMediaSessions`
- `render`
- `state.mediaConnected`

Primary suspect to prove/reject: a stale SSE/UI refresh invalidating, replacing or disconnecting a valid in-flight connection attempt.

Do not create a replacement session for a late participant. Do not rewrite backend lifecycle without evidence.

Required regression cases:

- Mobile first, wait >=30s, Desktop joins.
- Desktop first, wait >=30s, Mobile joins.
- Mobile first, wait >=60s, Desktop joins.
- Desktop first, wait >=60s, Mobile joins.
- Simultaneous join.
- Repeated Join does not duplicate session/participant.

All cases must converge on the same media session/LiveKit room.

### P0-2 — Radio raw realtime audio missing on Mobile

Observed:

Desktop speaks in Radio. Mobile receives translated text/TTS but does not hear the real Desktop voice.

Trace independently:

`Desktop mic -> local LiveKit publication -> remote publication -> Mobile TrackSubscribed -> GroupMediaPresentation.remote() -> attached AUDIO element -> output route -> play() -> currentTime/progression`

Classify the proven failure, for example:

- `track_not_published`
- `track_not_subscribed`
- `track_not_attached`
- `playback_blocked`
- `output_unavailable`

Verify the actual LiveKit JS version used by this repository before calling audio-unlock APIs. If supported/required, use the installed version's real contract for room audio playback/unlock; do not guess API names.

If mobile autoplay requires a gesture, expose an explicit user recovery control instead of silently retaining `playbackBlocked=true`.

Required physical behavior:

- Translation OFF: Desktop raw speech is audible on Mobile.
- Translation ON: Desktop raw speech remains audible and translated FINAL/TTS also works.

### P1-1 — Mobile Auto Read first-use failure

Observed:

- Auto Read already ON.
- First incoming translated FINAL does not speak.
- Manual `Play on this device` once, or OFF/ON Auto Read, makes later items work.
- UI can report speech unsupported even though manual speech later works.

Implement deterministic readiness states equivalent to:

- `LOCKED` / `UNLOCK_REQUIRED`
- `VOICE_LOADING`
- `READY`
- `PLAYING`
- `BLOCKED`
- `UNSUPPORTED`
- `ERROR`

Do not classify activation, autoplay block, voice loading or start timeout as `UNSUPPORTED`.

A valid user gesture may establish speech readiness. If a translated FINAL arrives before readiness, queue it and keep it retryable.

Critical rule: automatic playback must not be marked consumed before actual TTS `onstart`.

Acceptance:

- Auto Read ON from the beginning.
- First incoming FINAL is spoken.
- No manual Play primer.
- No Auto Read OFF/ON workaround.

### P1-2 — Group Call Translation Plugin missing

Video already mounts Group Translation. Audio Call does not.

Reuse existing Group Translation V2.

Call runtime contract:

- `runtime_kind=call`
- `runtime_id=<current audio media session>`
- existing Group-owned local audio track

Desktop and Mobile active Call must support:

- text translation
- voice recording/translation
- translated result
- Auto Read
- history
- collapse/expand

Do not create another Call translation backend.

Extend `GroupCommunicationWorkspace` so Call is a supported communication workspace without forcing Video-specific sizing semantics onto audio Call.

Presentation/runtime identity must be distinct:

- `call:<session_id>`
- `video:<session_id>`
- `radio:<runtime_id>`

Do not use `video:<id>` for Call.

### P1-3 — Shared Group Space picker for Call/Video

Add in-surface Group Space picker to:

- Call Desktop
- Call Mobile
- Video Desktop
- Video Mobile

Reuse:

- `state.spaces`
- existing `GroupSpace`
- existing `select-space` patterns
- Radio picker UX where appropriate

Do not create another room API.

Mobile controls must be touch-safe (>=44x44 CSS px).

Active session switching must be lifecycle-safe.

For active Call/Video:

`choose new space -> confirm leave if needed -> semantic POST current /leave -> disconnect current transport -> select target GroupSpace -> load target space/session`

Never only disconnect LiveKit and switch space while the server still considers the participant joined.

For Radio, release/stop floor safely before leave/switch.

### P2 — Mobile Call/Video start layout

Observed:

The member picker sits too high and covers or clips the media icon/title/description. The primary CTA can sit too close to the bottom navigation.

Do not fix with negative margins, transform hacks or another arbitrary fixed height.

Use layout reservation:

- icon/title/description: visible, non-overlapping, non-shrinking region
- 12–20px logical gap before picker
- member form: flexible `minmax(0, 1fr)` style region
- member list: scrolling region
- primary CTA: reachable above bottom nav and `safe-area-inset-bottom`

Target includes `390x844` portrait and one shorter-height mobile viewport.

---

## Primary frontend files

- `app/static/group-v3/group_v3_app.js`
- `app/static/group-v3/group_communication_workspace.js`
- `app/static/group-v3/group_media_presentation.js`
- `app/static/group-v3/group_tts_manager.js`
- `app/static/group-v3/group_v3_translation.js`
- `app/static/group-v3/group_translation_view.js`
- `app/static/group-v3/group_device_manager.js`
- `app/static/group-v3/group_radio_ui.js`
- `app/static/group-v3/group_v3_corrective.css`
- `app/static/group-v3/group_v3_runtime.css`
- `app/static/group-v3/group_v3_room_closure.css`
- `app/static/group-v3/group_v3_translation_v2.css`
- `app/static/group-v3/group_v3_i18n.js`
- `app/templates/group_communication_v3.html`

## Inspect backend only as needed

- `app/group_v3/session_service.py`
- `app/group_v3/session_router.py`
- `app/group_v3/session_schemas.py`
- `app/group_v3/media.py`
- `app/group_v3/events.py`
- `app/group_v3/radio_service.py`
- `app/group_v3/radio_router.py`
- `app/group_v3/translation_service.py`
- `app/group_v3/translation_router.py`
- `app/group_v3/translation_schemas.py`
- `app/models.py`

If a DB migration appears necessary, stop before creating it and report the proven blocker.

---

## Regression contract

Add/update deterministic regression tests for:

1. late second participant joins ACTIVE media session;
2. join order A -> B;
3. join order B -> A;
4. simultaneous join;
5. repeated Join idempotency;
6. stale SSE refresh cannot cancel a valid media connection;
7. raw audio subscribed/attached path;
8. blocked raw audio exposes recovery state;
9. first Auto Read FINAL remains retryable until real TTS `onstart`;
10. activation-required is not reported as unsupported;
11. voice-loading is not reported as unsupported;
12. Call Translation dock mounted Desktop/Mobile;
13. Call runtime uses `runtime_kind=call`;
14. Call Translation uses Group-owned audio track;
15. `TRANSLATION_SECOND_GET_USER_MEDIA=0` for healthy active Call;
16. Call room picker Desktop/Mobile;
17. Video room picker Desktop/Mobile;
18. active media room switch performs semantic leave;
19. mobile media-start icon/title remains visible;
20. CTA remains reachable above bottom nav/safe area.

Protect existing behavior:

- Direct 1:1 unchanged
- existing Video Translation unchanged except corrective fixes required here
- existing Radio room picker unchanged except corrective fixes required here
- Group history and permissions unchanged

---

## Execution workflow

1. Verify lineage before editing:
   - `CURRENT_PR35_HEAD`
   - `CURRENT_MAIN_SHA`
   - `CURRENT_RENDER_LIVE_SHA` if accessible
   - `OWNER_DEPLOYED_SHA` if determinable
2. Continue from the latest PR #35 task head. Do not restart from `main`.
3. Implement continuously across the blocker set. Do not stop for owner/prod QA between phases.
4. Focused developer checks during implementation are allowed to prevent obvious breakage.
5. After implementation is frozen, run one final local validation gate:
   - JavaScript/static validation
   - focused Python tests
   - deterministic browser tests
   - mobile `390x844` rendered validation
   - Render contract tests
   - source-lock validation
6. Do not claim deterministic browser QA proves physical iPhone TTS/autoplay or real two-device LiveKit behavior.
7. Push the exact tested candidate to the same PR #35 branch.
8. Verify `TESTED_COMMIT_SHA == REMOTE_PR_HEAD_SHA`.
9. Report exact candidate SHA and STOP for owner deploy/physical QA.

## Release gate

The next feature/update phase remains blocked until the owner deploys the final candidate and reports PASS for the full current corrective scope.

Required owner QA after candidate deployment:

- Video Mobile-first delayed Desktop join: PASS
- Video Desktop-first delayed Mobile join: PASS
- simultaneous Video join: PASS
- Radio raw audio Translation OFF: PASS
- Radio raw audio Translation ON + translated TTS: PASS
- first Auto Read translated FINAL: PASS without manual primer
- Call Translation Desktop: PASS
- Call Translation Mobile: PASS
- Call Translation uses no second microphone owner: PASS
- Call Group Space picker Desktop/Mobile: PASS
- Video Group Space picker Desktop/Mobile: PASS
- active room switch leaves old media session safely: PASS
- Mobile Call/Video start heading and CTA geometry: PASS

Only after this owner QA is PASS may work proceed to the next update.

## Final executor report

Return at minimum:

```text
STATUS=
BASE_SHA=
CURRENT_MAIN_SHA=
CURRENT_RENDER_LIVE_SHA=
PR_NUMBER=35
FINAL_COMMIT_SHA=
REMOTE_PR_HEAD_SHA=

VIDEO_ASYNC_JOIN_FIX=
VIDEO_JOIN_A_TO_B_TEST=
VIDEO_JOIN_B_TO_A_TEST=
VIDEO_JOIN_SIMULTANEOUS_TEST=
VIDEO_JOIN_DUPLICATE_TEST=

RADIO_RAW_AUDIO_FIX=
RAW_AUDIO_TRANSLATION_OFF_TEST=
RAW_AUDIO_TRANSLATION_ON_TEST=
AUDIO_PLAYBACK_RECOVERY=

AUTO_READ_FIRST_USE_FIX=
TTS_ACTIVATION_STATE_MACHINE=
FIRST_FINAL_RETRY_UNTIL_ONSTART=

CALL_TRANSLATION_PLUGIN_DESKTOP=
CALL_TRANSLATION_PLUGIN_MOBILE=
CALL_TRANSLATION_SECOND_GET_USER_MEDIA=
CALL_RUNTIME_KEY=

CALL_ROOM_PICKER_DESKTOP=
CALL_ROOM_PICKER_MOBILE=
VIDEO_ROOM_PICKER_DESKTOP=
VIDEO_ROOM_PICKER_MOBILE=
ACTIVE_ROOM_SWITCH_SEMANTIC_LEAVE=

MOBILE_CALL_LAYOUT=
MOBILE_VIDEO_LAYOUT=

BACKEND_CHANGED=
DATABASE_CHANGED=
MIGRATION_CREATED=
DIRECT_1_1_CHANGED=
ENV_CHANGED=

JS_CHECK=
PYTHON_FOCUSED_TESTS=
BROWSER_TESTS=
MOBILE_390X844=
RENDER_CONTRACT=
SOURCE_LOCK=

OWNER_MANUAL_IPHONE_QA=PENDING
OWNER_MANUAL_TWO_DEVICE_QA=PENDING
MERGED=NO
DEPLOYED=NO
READY_FOR_OWNER_DEPLOY_QA=YES/NO
```

If `READY_FOR_OWNER_DEPLOY_QA=YES`, provide exactly the commit SHA the owner should deploy. Then stop.