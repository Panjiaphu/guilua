# Group Media Dual-Provider + Admin Routing Contract v1.0

Status: **OWNER-APPROVED FUTURE ARCHITECTURE / NOT YET EXECUTABLE**
Decision date: **2026-09-06**
Primary repo: `Panjiaphu/AI-COMMUNICATION-Timeblock`
Companion control surface: Timeblock Admin in `Panjiaphu/fumap-bot-life`

This contract defines how Group Call, Group Video and Group Radio may run on either LiveKit Cloud or Cloudflare Realtime SFU without duplicating the Group application source tree.

## 1. Canonical architecture

There is one Group Communication application and one provider-neutral Group Media contract.

```text
GROUP MEDIA CONTRACT v1
├── livekit-v1
└── cloudflare-realtime-v1
```

Do not create separate application codebases such as `source-livekit/` and `source-cloudflare/`.

Provider switching affects only Group media transport:

```text
Group Call audio
Group Video audio/video
Group Radio live audio
```

It must not change:

```text
Group Chat
Group membership/roles
Group history
attachments/pins/reactions
PostgreSQL source of truth
Valkey Radio floor ownership
OpenAI STT/translation
shared translation variants
local TTS
Direct 1:1 ownership/runtime
```

## 2. Ownership boundary

`AI-COMMUNICATION-Timeblock` remains the sole Group domain owner and the source of truth for media-provider policy enforcement.

Timeblock Admin may expose the owner-facing provider control UI, but it must call a server-to-server authorized AI-COMMUNICATION admin/control API. Timeblock Admin must not directly mutate Group provider tables or provider secrets.

```text
TIMEBLOCK ADMIN
    -> authorized server-to-server control request
AI-COMMUNICATION
    -> validates owner/admin policy
    -> stores provider routing policy
    -> applies policy to NEW media sessions
```

Provider credentials remain server-only environment secrets in the AI-COMMUNICATION runtime.

## 3. Provider-neutral backend contract

Application/domain services must depend on a provider-neutral contract, not directly on `LiveKitGroupMediaProvider`.

Target contract responsibilities:

```text
GroupMediaProvider

health()
usage_snapshot()
create_connection()
negotiate_connection()
publish_audio()
publish_video()
unpublish_track()
subscribe_tracks()
update_subscriptions()
close_track()
close_connection()
```

Provider implementations:

```text
LiveKitMediaProviderV1
CloudflareRealtimeMediaProviderV1
```

Exact method names may vary if current source makes a smaller clean abstraction possible, but the application layer must not require LiveKit-specific room/JWT/identity semantics.

## 4. Provider-neutral frontend contract

The browser application must not call `window.LivekitClient` from Group business/UI logic after abstraction.

Target browser contract:

```text
GroupMediaClient

connect()
disconnect()
publishAudio()
publishVideo()
unpublish()
enableMic()
disableMic()
enableCamera()
disableCamera()
subscribe()
unsubscribe()
setPreferredQuality()
onTrackAdded()
onTrackRemoved()
onReconnect()
onDisconnect()
```

Adapters:

```text
LiveKitMediaClientV1
CloudflareRealtimeMediaClientV1
```

Group Call/Video/Radio UI must use the common client contract.

## 5. Session pinning is mandatory

Provider routing policy is evaluated exactly once when a new Group media session is created.

The chosen provider is persisted on the application session:

```text
GroupMediaSession.provider_key = livekit | cloudflare
```

After creation, reconnect/grant/negotiation operations must use that session's pinned `provider_key`, not the current admin default.

Example:

```text
10:00 default=livekit
Room A created -> provider=livekit

10:15 admin switches default=cloudflare
Room A remains livekit
Room B created at 10:16 -> provider=cloudflare
```

## 6. No hot-switch of active rooms in v1

An active LiveKit room must never be silently migrated to Cloudflare, and an active Cloudflare session must never be silently migrated to LiveKit.

Provider changes apply to **new sessions only**.

Use drain switching:

```text
NORMAL
-> current default accepts new sessions

DRAIN
-> old provider keeps existing sessions
-> old provider receives no new sessions
-> new provider receives new sessions

COMPLETE
-> old provider active sessions = 0
```

A future explicit reconnect/migration protocol is a separate task and is not part of v1.

## 7. Admin routing policy

Provider policy is durable application state, not a Render environment variable changed manually for each switch.

Secrets/config remain in environment:

```text
LiveKit URL/API key/API secret
Cloudflare Realtime App ID/App Secret
```

Routing policy is stored in the AI-COMMUNICATION database, conceptually:

```text
MediaProviderPolicy

default_provider
call_provider
video_provider
radio_provider
switch_mode
fallback_provider
changed_by
changed_at
change_reason
```

Allowed values:

```text
default_provider = livekit | cloudflare
call_provider = inherit | livekit | cloudflare
video_provider = inherit | livekit | cloudflare
radio_provider = inherit | livekit | cloudflare
switch_mode = normal | drain
fallback_provider = none | livekit | cloudflare
```

V1 production default after implementation remains:

```text
DEFAULT_PROVIDER=livekit
FALLBACK_PROVIDER=livekit
```

until Cloudflare has passed owner physical QA and is explicitly enabled.

## 8. Admin UI behavior

Timeblock Admin should expose a `Communication Media Provider` control surface showing:

```text
Mode: Manual (v1)
Default provider
Per-feature provider overrides
Provider health
Provider usage
Current active sessions by provider
Warning/critical thresholds
Drain status
Last switch actor/time/reason
```

Required actions:

```text
Route NEW sessions to LiveKit
Route NEW sessions to Cloudflare
Drain LiveKit -> Cloudflare
Drain Cloudflare -> LiveKit
Rollback NEW sessions to LiveKit
```

Admin UI must clearly state:

```text
Existing active sessions are not interrupted.
Provider change affects new sessions only.
```

## 9. Health and safety gate

Admin must not be offered a misleading "safe switch" if the target provider is unconfigured or unhealthy.

At minimum provider status should distinguish:

```text
UNCONFIGURED
HEALTHY
DEGRADED
UNAVAILABLE
```

Routing checks should include available provider configuration plus a bounded provider synthetic/health signal.

A switch decision must never be based only on cost/quota percentage.

Useful telemetry:

```text
usage / quota estimate
connection success rate
recent connection failures
reconnect rate
latency where available
active session count
provider health
```

## 10. Manual routing first; automatic routing later

V1 is owner/admin manual routing only.

Do not implement automatic quota-triggered provider switching in v1.

Future v2 may add cost-aware routing only after enough production telemetry exists, for example:

```text
IF LiveKit warning threshold exceeded
AND Cloudflare is HEALTHY
THEN route NEW Radio sessions to Cloudflare
```

Automatic routing requires a separate owner-approved task.

## 11. Fallback semantics

Fallback may occur only before a new session is committed/pinned to a provider, or through an explicitly designed create-session fallback transaction.

If requested Cloudflare creation fails and policy allows LiveKit fallback:

```text
requested_provider=cloudflare
actual_provider=livekit
fallback_reason=<truthful bounded code>
```

The resulting session is pinned to LiveKit for its lifetime.

Do not dynamically flip an already-created session to another provider during reconnect.

## 12. Database/provider identifiers

Current LiveKit-specific business fields such as:

```text
livekit_room_name
livekit_identity
```

must be neutralized during the provider-abstraction phase.

Canonical durable domain identifiers remain:

```text
application media session ID
membership ID
space ID
media kind
provider key
session lifecycle
```

Provider-specific session/track identifiers should remain ephemeral or provider-runtime metadata wherever practical.

Video subscription preference must be expressed in application membership/session identities, not provider-specific participant IDs.

Example:

```text
Domain:
viewer A wants B,C,D

LiveKit adapter:
B,C,D -> LiveKit participant identities

Cloudflare adapter:
B,C,D -> Cloudflare published track IDs
```

## 13. Radio contract

Radio floor ownership remains in Valkey and must stay provider-neutral.

```text
floor acquire
-> provider adapter enables/publishes speaker audio
-> listeners receive one active speaker track

floor release
-> release application floor immediately
-> stop/close/update provider audio transmission
-> transient local recording may finish
-> STT once
-> shared text translation variants
```

Provider work must not delay floor release.

## 14. Video contract

Both provider implementations must honor one application quality/subscription policy for rooms up to 10 participants.

Target policy:

```text
active speaker / focus tile -> highest required layer
visible secondary tiles -> medium/low layer
small/offscreen tiles -> low or unsubscribe
camera off -> no video publication
mobile -> conservative subscription set
```

Do not encode LiveKit-specific `dynacast`/identity semantics into business logic. Cloudflare-specific track/RID semantics also stay inside the adapter.

## 15. Canonical participant limit

Owner product limit:

```text
GROUP_MEDIA_MAX_PARTICIPANTS=10
```

Call, Video, Radio, backend validation, frontend UI and both provider adapters must share the same canonical application limit.

Any existing source hardcode of `8` is technical debt to remove during provider abstraction.

## 16. Rollout sequence

This project is not one giant production PR. Execute as four bounded stages after all prerequisites are satisfied:

```text
A. Media Provider Abstraction V1
   - behavior remains LiveKit
   - remove provider coupling
   - canonical 10-participant contract

B. Cloudflare Realtime Provider V1
   - add backend/client Cloudflare adapters
   - default remains LiveKit
   - Cloudflare disabled for production routing until QA

C. Admin Media Routing Control
   - AI-COMMUNICATION policy source of truth
   - Timeblock Admin control surface
   - health/usage/drain/rollback

D. Dual Provider QA + Production Enablement
   - Call -> Radio -> Video
   - Desktop/Mobile/iPhone physical QA
   - LiveKit rollback retained
```

## 17. Hard sequencing dependency

Do not start production implementation of this project while current Group corrective or Group Chat migration work is active.

Required predecessor order:

```text
1. Group V3 R1 corrective -> owner QA PASS
2. Group Chat shared-variant/speaker-funded translation migration -> owner QA PASS
3. Resolve exact resulting production/main continuation SHA
4. Create executable PLAN_SHA from that exact lineage
5. Start Dual Provider project
```

Until step 3 is complete:

```text
DUAL_PROVIDER_EXECUTION_STATUS=QUEUED_BLOCKED
PRODUCTION_CODE_CHANGES_ALLOWED=NO
```

## 18. Protected boundaries

This contract does not authorize:

- Direct 1:1 ownership/runtime rewrite;
- moving Group durable data to Cloudflare;
- replacing PostgreSQL/Valkey with Cloudflare products;
- moving OpenAI translation to a media provider;
- putting provider secrets in browser/admin HTML;
- hot-switching active sessions;
- auto-routing without a later owner-approved task;
- merging/deploying before owner QA;
- removing LiveKit rollback before Cloudflare production acceptance.
