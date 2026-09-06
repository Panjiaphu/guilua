# TB-GROUP-MEDIA-DUAL-PROVIDER-20260906-001

Status: **PLANNED / QUEUED / BLOCKED BY PREDECESSORS**
Planner: ChatGPT GPT-5.6 Sol
Target executor: fresh Codex GPT-5.6 Sol High
Repository: `Panjiaphu/AI-COMMUNICATION-Timeblock`
Companion repository for Admin UI only: `Panjiaphu/fumap-bot-life`

## 1. Do not execute yet

This task is intentionally parked for later execution.

Required predecessor sequence:

```text
PREDECESSOR_1=Group V3 R1 corrective PR #35 -> owner deploy QA PASS
PREDECESSOR_2=Group Chat shared-variant/speaker-funded translation task -> owner deploy QA PASS
PREDECESSOR_3=resolve exact resulting production/main continuation SHA
```

Until all three are true:

```text
EXECUTION_ALLOWED=NO
PRODUCTION_CODE_CHANGES_ALLOWED=NO
CODEX_MUST_NOT_START_IMPLEMENTATION=YES
```

When predecessors complete, Planner must refresh this task with the exact executable starting SHA and a new PLAN_SHA before Codex touches production code.

## 2. Binding architecture

Read first:

```text
docs/engineering/GROUP_MEDIA_DUAL_PROVIDER_ADMIN_ROUTING_CONTRACT.md
```

The project must implement one provider-neutral Group Media contract with two providers:

```text
livekit-v1
cloudflare-realtime-v1
```

No duplicate application source tree is allowed.

## 3. Final product behavior

Timeblock Admin exposes owner/admin controls for Group media provider routing.

Default v1 behavior:

```text
MODE=MANUAL
DEFAULT_PROVIDER=livekit
ACTIVE_SESSIONS_HOT_SWITCH=NO
NEW_SESSIONS_ONLY=YES
LIVEKIT_ROLLBACK=REQUIRED
```

Admin may choose a default provider and optional per-feature overrides for:

```text
Group Call
Group Video
Group Radio
```

Group Chat does not use either media provider.

## 4. Session pinning

Every new Group media session must persist its selected provider:

```text
provider_key = livekit | cloudflare
```

A provider change in Admin must affect only sessions created after the policy change.

Existing sessions stay on their original provider through reconnect and completion.

## 5. Safe drain switch

Required control behavior:

```text
LiveKit active session A -> remains LiveKit
Admin switches default to Cloudflare
Cloudflare new session B -> Cloudflare
No active-session interruption
```

Admin must support drain/rollback semantics rather than live migration.

## 6. Backend abstraction target

Refactor current LiveKit-specific media implementation behind a provider-neutral contract. Preserve behavior while LiveKit remains the only enabled production provider during phase A.

Primary current coupling to remove/neutralize includes, but is not limited to:

```text
app/group_v3/media.py
app/group_v3/session_service.py
app/group_v3/radio_service.py
app/core/config.py
app/main.py
app/models.py
```

Current LiveKit-specific domain terms such as `livekit_room_name` and `livekit_identity` must not remain canonical business-domain identifiers after the abstraction migration.

## 7. Frontend abstraction target

Remove LiveKit SDK coupling from Group application/UI logic.

Primary current coupling includes:

```text
app/static/group-ui/livekit_group_session.js
app/static/group-v3/group_v3_app.js
```

Create a common Group media client contract with separate adapters:

```text
LiveKitMediaClientV1
CloudflareRealtimeMediaClientV1
```

Do not make Group Call/Video/Radio UI branch directly on provider-specific SDK APIs except inside adapters.

## 8. Canonical participant limit

Owner product contract:

```text
GROUP_MEDIA_MAX_PARTICIPANTS=10
```

Remove source hardcodes of `8` and make backend/frontend/provider adapters consume the same canonical limit.

## 9. Cloudflare provider phase

After abstraction is stable on LiveKit, add Cloudflare Realtime SFU integration.

Rules:

```text
Cloudflare App Secret = server-only
Cloudflare = ephemeral media transport only
AI-COMMUNICATION remains room/membership/authorization source of truth
PostgreSQL remains durable Group storage
Valkey remains Radio floor authority
OpenAI remains STT/translation provider
```

Do not move Group durable state to Cloudflare.

## 10. Admin control source of truth

Provider-routing policy belongs to AI-COMMUNICATION durable state.

Timeblock Admin is a control surface only and must use an authorized server-to-server API.

Conceptual policy:

```text
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

Provider secrets stay in the AI-COMMUNICATION runtime environment and never appear in the Admin UI.

## 11. Admin page requirements

Admin page must show:

```text
Current default provider
Per-feature provider override
LiveKit status/usage/active sessions
Cloudflare status/usage/active sessions
Warning threshold
Critical threshold
Drain state
Last provider change audit
```

Required actions:

```text
Route NEW sessions to LiveKit
Route NEW sessions to Cloudflare
Drain LiveKit -> Cloudflare
Drain Cloudflare -> LiveKit
Rollback NEW sessions to LiveKit
```

Required visible note:

```text
Existing active sessions are not interrupted. Provider changes apply to new sessions only.
```

## 12. Health gate

Do not route to an unconfigured/unavailable provider.

Provider status contract:

```text
UNCONFIGURED
HEALTHY
DEGRADED
UNAVAILABLE
```

Switch safety must consider both usage and health. Do not switch solely because LiveKit is near a quota threshold.

## 13. Rollout phases

Execute in bounded sequence after this task is unblocked:

```text
PHASE A - Media Provider Abstraction V1
  behavior stays LiveKit
  no production Cloudflare routing

PHASE B - Cloudflare Realtime Provider V1
  add backend/client adapter
  default stays LiveKit

PHASE C - Admin Media Routing Control
  AI policy source of truth
  Timeblock Admin UI/control API

PHASE D - Dual Provider QA + Production Enablement
  Call -> Radio -> Video
  desktop/mobile/iPhone
  switch/drain/rollback
```

Do not combine all four phases into one unbounded implementation pass.

## 14. QA requirements after implementation

At minimum prove:

```text
LIVEKIT_EXISTING_BEHAVIOR_PRESERVED=PASS
CLOUDFLARE_CALL=PASS
CLOUDFLARE_RADIO=PASS
CLOUDFLARE_VIDEO=PASS
SESSION_PROVIDER_PINNING=PASS
ADMIN_NEW_SESSION_SWITCH=PASS
ACTIVE_SESSION_NOT_INTERRUPTED=PASS
DRAIN_SWITCH=PASS
ROLLBACK_TO_LIVEKIT=PASS
UNHEALTHY_TARGET_BLOCKED=PASS
MAX_PARTICIPANTS_10=PASS
GROUP_CHAT_UNCHANGED=PASS
DIRECT_1_TO_1_UNCHANGED=PASS
POSTGRES_OWNERSHIP_UNCHANGED=PASS
VALKEY_RADIO_FLOOR_UNCHANGED=PASS
OPENAI_TRANSLATION_OWNERSHIP_UNCHANGED=PASS
```

Physical cross-device owner QA remains mandatory before production routing changes are considered accepted.

## 15. Codex stop condition

If Codex encounters this task before predecessors are complete, it must report exactly:

```text
STATUS=BLOCKED_BY_PREDECESSORS
TASK_ID=TB-GROUP-MEDIA-DUAL-PROVIDER-20260906-001
PRODUCTION_CODE_CHANGED=NO
NEXT_ACTION=WAIT_FOR_PLANNER_TO_RESOLVE_POST_CHAT_EXACT_START_SHA
```

and stop.

## 16. Planner reactivation requirements

After Group V3 corrective and Group Chat migration are owner-QA PASS, Planner must:

```text
1. verify current main
2. verify deployed/accepted SHA
3. verify Group Chat migration landed in the continuation tree
4. verify no unresolved media corrective branch remains
5. update exact START_SHA
6. update exact PLAN_SHA
7. give a fresh Codex execution prompt
```

Do not infer the future start SHA now.
