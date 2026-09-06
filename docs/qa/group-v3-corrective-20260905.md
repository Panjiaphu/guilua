# Group Video / Translation / Radio corrective — 2026-09-05

## Release boundary

- Repository: Panjiaphu/AI-COMMUNICATION-Timeblock.
- Same branch: codex/group-v3-media-lifecycle-p1; same PR #30.
- Starting HEAD/PR: cae7b0a1e383edaf42740d4dd172cb45803bb421.
- Observed main at start: f9653921949cad4b876fc9327c367acb7e2e9d33.
- One coding agent. No merge, no Render deployment, no production acceptance claim.
- Owner deploys the final remote PR HEAD reported with this delivery, then performs physical-device QA.
- Direct 1:1, the Timeblock repository and source-locked service-worker were not edited.

## Evidence and corrections

### Viewport and layout

Before edits, an isolated browser geometry probe using the production CSS load
order at 390x844 measured:

| Element | Baseline finding |
| --- | --- |
| native-mobile | grid rows 844px / 0px; bottom padding 62px |
| native-main | reserved rows 24px / 62px / 0px / 758px |
| surface-content | top 86px, height 758px |
| call-control-dock | two 44px button rows, total height 108px |
| collapsed translation | height 124px, including 52px safety layer |

The final workspace stylesheet owns active Group layout after nav/PWA styles.
It removes hidden navigation reservations, uses the existing VisualViewport
adapter, keeps collapsed Translation compact and reserves safety controls only
for open overlays. Portrait uses two stacked video tiles; touch landscape uses
two columns. FIT preserves the entire remote source; intentional letterboxing
inside a tile is distinct from unused white viewport space.

Browser assertions cover 390x844, 844x390 and 412x915, including exact content
height/bottom edge, one-row 44px+ controls, COLLAPSED/HALF/FULL and reversible
desktop MAXIMIZED/Translation arbitration. Explicit Translation opening has
priority over a previous Video MAX request; collapsing restores the preference.
No vertical text rail remains. Stage, tile, Translation and voice icons have
different meanings and accessible labels.

### Media ownership

GroupMediaPresentation holds stable local/remote media elements keyed by exact
track and participant identity. No first-tile fallback. Missing destinations
remain pending; repeated synchronization attaches a track only once. Normal
shell refresh relocates the same media element and retains the same Translation
panel, recorder and draft for the same runtime/surface/locale.

Layout/focus/hide/restore never acquire or publish media. Explicit focus toggles
back; hiding only affects presentation. Unsubscribe and disconnect clear owned
presentation references without stopping a primary track from the plugin.
Camera/microphone indicators reflect real local tracks rather than unconditional
true values. Muted/unmuted events refresh the video placeholder.

Read-only diagnostics: GroupMediaPresentation.diagnostics() returns identity,
SID, subscription/track state, pending/attached state, video dimensions,
currentTime, paused and playbackBlocked. It does not expose media content.

### Voice and Translation V2

- PREPARING/profile save is guarded against double clicks.
- READY mic -> RECORDING save/stop + elapsed -> STOPPING ->
  PROCESSING_STT -> TRANSLATING -> RESULT_READY mic or classified ERROR.
- TRANSLATING is driven by canonical segment visibility via existing Group SSE
  or projection of the synchronous POST result, not a fabricated timer.
- Only the Group runtime's live/enabled/unmuted audio track is wrapped. No
  getUserMedia, clone or stop of that primary track in the plugin.
- MIME negotiation supports WebM/Opus, MP4/M4A and Ogg with matching filenames;
  duration_seconds is sent using the existing backend contract.
- Empty audio is rejected visibly on the client and before provider invocation
  on the server. Recorder errors, profile errors, STT errors, variant errors,
  history sync errors and playback errors remain distinguishable.
- A successful POST is retained in the local canonical segment map even when
  subsequent GET history fails. A separate warning offers history-only retry.
- Failed language variants retry from the persisted source; STT is not repeated.
- Segment V2 ignores the legacy auto_translate_enabled switch in target
  selection, recipient projection and counts. Legacy translation code is intact.
- The source language is reused, not sent to a translation provider. Author
  history does not duplicate the source as a distributed variant. The sender
  is excluded from recipient counts; a zero-count language is not labelled
  delivered.
- Auto Read applies locally to new received FINAL results, never speaker
  previews or historical bootstrap rows. Deduplication does not publish audio.

GroupV3TranslationController.diagnostics() keeps a bounded in-memory list of
stage, HTTP status, safe failure code, runtime and segment ID. It excludes audio,
transcript, translated text, tokens and response bodies.

### Radio

The shared panel/state machine is used without redesigning the floor protocol.
PTT remains reachable through panel changes. In listen-only Radio with no usable
local track, Translation Record shows microphone preflight; it does not request
the floor or create a microphone owner. Existing backend Radio closure/floor
tests remain part of the final suite.

## Final verification

- Python suite: 236 passed, 32 skipped; one existing Starlette/httpx deprecation.
- Explicit browser suite: 20 passed (18 corrective integration cases and
  2 existing Chromium/WebKit viewport adapter cases).
- Python compilation and JavaScript syntax checks: pass.
- Alembic single-head, diff whitespace, scoped secret scan and exact remote SHA
  checks are recorded in the final delivery.
- Browser fixture loads the actual production template, CSS order and Group
  scripts. Authentication, API data, media SDK/streams and recorder error cases
  are deterministic test boundaries. Backend contracts/providers are separately
  exercised by the Python suite. No mocked service is added to production.
- Browser artifact directories are outside Git under the Windows temporary
  directory, prefixed group-corrective-final-20260905. Assertions include DOM
  identity and unchanged acquire/publish/attach counts; Chromium page errors
  fail the fixture. Screenshots were visually inspected.

A headless WebKit run is not an iPhone. Synthetic media is not a two-device
LiveKit/SFU/network or actual speech-provider test. Production logs from the
original reported incident were not available, so this report does not claim
the original voice/provider failure was conclusively reproduced.

## Owner manual QA after deploying final PR SHA

1. Confirm Render built the exact reported PR commit, not main or an older SHA.
2. Reload both desktop and installed iPhone PWA. Group asset URLs include a new
   corrective query version; the source-locked service-worker is unchanged.
3. Join the same Video room with two accounts. Check both directions of
   audio/video, FIT, camera/mic toggles, background/foreground and reconnect.
4. Test portrait/landscape, keyboard open/close, safe areas, Translation
   collapsed/half/full and desktop MAX -> open Translation -> close/restore.
5. Record vi/zh-TW/en. Confirm save indicator, one STT operation, recipient's
   preferred language, variant retry, history retry and local Auto Read.
6. Verify Radio PTT independently of Translation recording. Listen-only
   preflight must not request the floor. Verify Direct 1:1 remains unchanged.
7. For failure evidence, capture deployed SHA, device/browser, runtime/segment
   IDs and the bounded diagnostics above; do not share raw audio or secrets.

READY_FOR_OWNER_DEPLOY_QA is conditional on the final pushed/tested SHA checks.
OWNER_PHYSICAL_QA = PENDING. PRODUCTION_PASS = PENDING.
