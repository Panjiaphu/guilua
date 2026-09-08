# TB-GROUP-COLLAB-20260906-002 — PR #36 Group Collaboration Efficiency & Notifications

Status: **OWNER-APPROVED EXECUTION TASK / IMPLEMENT AFTER LINEAGE REFRESH**
Planner: ChatGPT GPT-5.6 Sol
Recommended executor: **Codex GPT-5.6 Sol / Reasoning Max**
Repository: `Panjiaphu/AI-COMMUNICATION-Timeblock`
PR: `#36`

## 0. Owner decision and exact starting state

PR #35 owner deploy QA is PASS and has been merged to `main`.

Canonical accepted Group V3 main baseline:

```text
ACCEPTED_MAIN_SHA=1dd41308b4fda33797b3de3b09c5bc13efd0b720
PR35_OWNER_QA=PASS
```

PR #36 was created as docs-only from an older main. Before production implementation, refresh the SAME PR #36 branch with current `origin/main` using a normal merge or another non-destructive/no-force lineage-safe method.

Required preflight:

```text
CURRENT_MAIN_SHA
CURRENT_PR36_HEAD
CURRENT_RENDER_LIVE_SHA
ACCEPTED_MAIN_SHA=1dd41308b4fda33797b3de3b09c5bc13efd0b720
```

Required ancestry after lineage refresh:

```text
1dd41308b4fda33797b3de3b09c5bc13efd0b720
must be an ancestor of the implementation candidate.
```

Do not restart from stale PR #36 source. Do not discard PR #35 accepted fixes. Do not force-push.

## 1. Mission

Finish PR #36 as one coherent Group collaboration update with three tightly bounded product tracks:

```text
A. Group Chat Shared Translation
B. Group Call/Video Incoming Ringtone Parity
C. Group Notification System
   C1. Group Chat
   C2. Group Call
   C3. Group Video
   C4. Group Radio
```

This update must optimize provider cost, reduce notification fatigue, preserve privacy, and keep Group ownership in AI-COMMUNICATION while Timeblock remains the delivery/control surface for internal notifications and Web Push.

## 2. Hard architecture boundaries

```text
GROUP_EMAIL=NO
GROUP_RESEND=NO
GROUP_SMTP=NO
RAW_GROUP_MESSAGE_COPIED_TO_TIMEBLOCK=NO
RAW_GROUP_TRANSLATION_COPIED_TO_TIMEBLOCK=NO
NOTIFICATION_FAILURE_BLOCKS_GROUP_ACTION=NO
DIRECT_1_1_CHANGED=NO
LIVEKIT_OWNERSHIP_REWRITE=NO
CLOUDFLARE_PROVIDER_WORK=NO
RADIO_RINGTONE=NO
RADIO_PTT_BURST_PUSH=NO
```

AI-COMMUNICATION is authoritative for:

```text
GroupSpace
membership
Group messages
Group Call/Video/Radio sessions
Group translation
Group notification eligibility/policy
```

Timeblock is authoritative for:

```text
Internal Inbox / Activity
badge delivery
Web Push subscriptions
VAPID transport
global push preferences
quiet hours
```

Do not create fake Timeblock messaging conversations for GroupSpace.
Do not let browser clients create trusted system notification events.

## 3. Track A — Group Chat Shared On-demand Requester-funded Translation

Existing authority remains:

```text
docs/qa/TB-GROUP-CHAT-20260906-001.md
docs/engineering/GROUP_TRANSLATION_SHARED_VARIANT_COST_CONTRACT.md
```

Canonical Group Chat translation identity:

```text
(message_id, message_fingerprint, target_language)
```

Required rules:

```text
SHARED_VARIANT=YES
ON_DEMAND=YES
REQUESTER_FUNDED=YES
REUSE_BEFORE_QUOTA_CHECK=YES
HISTORY_SOURCE_FIRST=YES
HISTORY_AUTO_TRANSLATE=NO
HISTORY_AUTO_READ=NO
AUDIO_PERSISTENCE=NONE
```

Provider work must coalesce before external invocation. Database UNIQUE-after-provider-call is insufficient.

Required request order:

```text
authorize
-> target == source? reuse source
-> lookup shared FINAL
-> if FINAL exists return free
-> acquire canonical reservation/lock
-> recheck FINAL
-> reserve requester quota only if still missing
-> ONE provider call
-> persist shared FINAL
-> settle requester cost only on successful provider work
```

Concurrent same-target requests must produce one provider call and one payer.

## 4. Track B — Group Call/Video incoming ringtone parity

Current Group Call/Video incoming ringtone already exists. Do not rebuild from zero. Upgrade it toward Direct 1:1-quality semantics while preserving Group runtime ownership.

Required behavior:

```text
CALL incoming invited recipient -> ringtone
VIDEO incoming invited recipient -> ringtone
caller -> ringback only
RADIO -> no ringtone
```

Ringtone must stop on:

```text
accepted
rejected
cancelled
ended
expired/missed
room switch
session replacement
logout/runtime teardown
```

Required quality:

```text
volume preference
ring duration preference
single audible owner across multiple tabs
user-gesture/WebKit audio arm path
safe iOS foreground behavior
no conflict with Group TTS
preserve outgoing ringback
```

Do not claim custom continuous ringtone when an iPhone Home Screen web app is closed/backgrounded. Foreground eligible runtime may use custom ringtone; background delivery is OS Web Push/Notification behavior.

## 5. Track C — Group Notification System

### 5.1 Design principle

```text
MESSAGE DELIVERY != INTERRUPTIVE NOTIFICATION DELIVERY
```

Every Group message remains realtime. Notifications pass through a policy engine.

Default per-GroupSpace notification mode:

```text
smart
```

Supported modes:

```text
smart
all
important
none
```

Semantics:

```text
smart:
  normal message -> first-unread transition / aggregated activity
  direct reply -> immediate targeted activity
  structured mention -> immediate targeted activity IF a canonical structured mention model exists

all:
  normal messages eligible, but still coalesced/rate-limited and same-space-active suppressed

important:
  replies / structured mentions / invitations / important lifecycle events only

none:
  no Timeblock notification and no Web Push; unread state remains in GroupSpace
```

Do not infer mentions from display-name regex. If no structured mention identity exists, defer mention notification rather than shipping an unsafe heuristic.

### 5.2 Group Chat policy

Canonical policy:

| Event | Timeblock Internal | Web Push | Custom ringtone | Email |
|---|---:|---:|---:|---:|
| normal chat message | smart/aggregated | OFF by default; only if user opts into `all` | NO | NO |
| direct reply to my message | YES | conditional by Timeblock prefs/quiet hours | NO | NO |
| structured mention | YES | conditional by Timeblock prefs/quiet hours | NO | NO |
| Group invitation | YES | YES if allowed | NO | NO |
| member added/removed | activity only | NO default | NO | NO |
| message edit/delete | NO | NO | NO | NO |
| reaction | NO | NO | NO | NO |
| pin | activity only / optional | NO default | NO | NO |
| translation FINAL | NO | NO | local TTS only | NO |

### 5.3 First-unread aggregation

For normal Chat in `smart` mode:

```text
unread 0 -> 1
=> create one logical Timeblock activity alert

unread 1 -> N
=> do not create N additional interruptive alerts
=> update Group unread/badge state only

user opens GroupSpace and advances last_seen_sequence
=> notification pending state clears

next 0 -> 1 transition
=> one new logical activity alert is allowed
```

This prevents message bursts from becoming notification bursts.

### 5.4 Presence suppression

If the recipient is actively viewing the SAME GroupSpace and the document/app is visible:

```text
realtime message=YES
unread state=as appropriate
Timeblock internal interruptive alert=NO
Web Push=NO
sound=NO
```

Use short-lived presence, preferably Valkey/Redis TTL rather than durable PostgreSQL activity rows.

Recommended state shape:

```text
principal
membership_id
space_id
surface
visible
last_seen
```

Recommended TTL direction: 60-90 seconds, finalized from current runtime heartbeat cadence.

Presence failure must never lose the Group message. If presence is unknown, notification policy may fail toward a conservative eligible state, but message delivery remains authoritative.

### 5.5 Web Push strategy

Normal Group Chat messages must NOT Web Push by default in Smart mode.

Default push priorities:

```text
reply / structured mention / invitation -> eligible
normal message -> internal aggregated activity only
normal message Web Push -> only when per-GroupSpace mode=`all` and Timeblock global preferences permit
```

Timeblock still enforces:

```text
push_enabled
quiet hours
category preferences
active subscription validity
OS/browser permission
```

Use Group-specific notification namespaces/tags. Do not masquerade Group events as Direct 1:1 events.

Suggested semantics:

```text
group.chat.activity
group.chat.reply
group.chat.mention
group.call.incoming
group.call.missed
group.video.incoming
group.video.missed
group.radio.invited
group.radio.started
```

Normal Chat OS notification tag should coalesce by GroupSpace, e.g. semantic identity `group-chat:<space_id>` rather than one tag per message.

### 5.6 Group Call / Video notification policy

```text
group.call.incoming  -> Internal YES, Web Push YES if allowed, custom ringtone foreground YES, email NO
group.video.incoming -> Internal YES, Web Push YES if allowed, custom ringtone foreground YES, email NO
group.call.missed    -> Internal YES, Web Push conditional, ringtone NO, email NO
group.video.missed   -> Internal YES, Web Push conditional, ringtone NO, email NO
```

Incoming call/video notification TTL must be short and tied to session validity. A delayed push must not reopen or falsely present an ended ringing session as active.

### 5.7 Group Radio notification policy

```text
group.radio.invited -> Internal YES, Web Push conditional, ringtone NO
group.radio.started -> Internal YES, Web Push optional/conditional, ringtone NO
PTT floor acquire/release/burst -> Internal NO, Web Push NO, ringtone NO
```

Do not notify every Radio speaker change or burst.

## 6. Privacy contract

Timeblock Group notification records must contain metadata only:

```text
event_kind
space_id
resource_id/message_id/session_id
sender/initiator identity needed for display
group display title if already authorized/safe
created_at
deep-link/handoff metadata
```

Do not copy decrypted Group message body, attachment body, transcript, translation text, media tokens, or LiveKit grants into Timeblock notification storage.

A safe default Chat notification copy is semantic, e.g. "New activity in <Group> — open the group to view." Message preview must not require copying raw Group content into Timeblock.

## 7. Trusted cross-system delivery

Required flow:

```text
AI-COMMUNICATION Group business transaction COMMIT
-> durable Group event/outbox
-> Group Notification Dispatcher
-> recipient eligibility + per-space policy + presence
-> trusted server-to-server Timeblock notification ingest
-> Timeblock Internal Inbox / badge
-> optional Web Push
```

Use the existing server-authenticated Timeblock integration pattern. Do not invoke `/api/internal-messages/send` from the browser to impersonate a system event.

Create a dedicated, server-authenticated Group notification ingest contract if current Timeblock endpoints are not semantically appropriate.

Notification dispatch must be asynchronous from Group action success:

```text
Group message/session creation succeeds
Timeblock temporarily unavailable
=> Group action remains successful
=> notification remains pending/retryable
```

## 8. Idempotency and delivery ledger

Cross-system retry must create ONE logical notification per recipient/event/class.

Required semantic key:

```text
(group_event_id, recipient_principal, notification_class)
```

Example:

```text
group:<event_id>:member:<recipient_id>:chat-activity
```

Retrying the same event must not create duplicate internal alerts, badge increments, or repeated Web Push work.

Use a dedicated receipt/ledger if current Timeblock storage cannot guarantee this safely. Do not rely only on fuzzy context JSON search.

## 9. Deep-link / handoff behavior

Timeblock notification click must use the secure Group handoff path and then open the authorized AI-COMMUNICATION Group surface.

Targets:

```text
Chat -> GroupSpace + surface=chat + message anchor when still valid
Call -> GroupSpace + surface=call + session when still valid
Video -> GroupSpace + surface=video + session when still valid
Radio -> GroupSpace + surface=radio
```

If resource was deleted/ended, fall back gracefully to the GroupSpace surface.
If membership was removed, deny access normally and treat the notification as stale.
Notification deep links must never bypass membership authorization.

## 10. Settings UX

Add GroupSpace notification settings without cluttering core chat UI.

Target compact control:

```text
Notifications
- Smart — recommended
- All messages
- Important only
- Off

Mute temporarily
- 15 minutes
- 1 hour
- 8 hours
- 24 hours
- Until re-enabled
```

Do not add global duplicate VAPID/push subscription settings in AI-COMMUNICATION; Timeblock owns global/device delivery preferences.

## 11. Files — AI-COMMUNICATION inspect first

At minimum inspect:

```text
app/models.py
app/group_v3/service.py
app/group_v3/events.py
app/group_v3/router.py
app/group_v3/schemas.py
app/group_v3/chat_translation_service.py
app/group_v3/translation_service.py
app/group_v3/translation_router.py
app/group_v3/translation_schemas.py
app/group_v3/session_service.py
app/group_v3/session_router.py
app/group_v3/radio_service.py
app/group_v3/radio_router.py
app/integrations/timeblock/client.py
app/bff/proxy.py
app/main.py

app/static/group-v3/group_v3_app.js
app/static/group-v3/group_incoming_ringtone.js
app/static/group-v3/group_ringback.js
app/static/group-v3/group_communication_workspace.js
app/static/group-v3/group_v3_translation.js
app/static/group-v3/group_translation_view.js
app/static/group-v3/group_tts_manager.js
app/static/group-v3/group_v3_i18n.js
app/static/service-worker.js
app/templates/group_communication_v3.html

alembic/versions/<NEW_FORWARD_MIGRATION>.py
```

Likely new bounded modules are acceptable if source evidence supports them:

```text
app/group_v3/notification_service.py
app/group_v3/notification_schemas.py
app/group_v3/notification_presence.py
```

Do not create modules just to match this suggested naming if current architecture has a cleaner existing owner.

## 12. Files — Timeblock inspect first

At minimum inspect the canonical Timeblock repository and current main before changes:

```text
routes/communication_handoff.py
routes/internal_messages.py
routes/assistant_notifications.py
models/internal_message.py
models/assistant_notification.py
models/push_subscription.py
services/web_push_service.py
static/service-worker.js
app.py
```

Reference only unless genuinely required:

```text
services/messaging_call_notification_service.py
services/call_notification_delivery_service.py
services/call_push_delivery_service.py
static/js/call-v1/ring-audio.js
```

Do NOT route Group through the Direct email path.

Potential dedicated bounded modules/endpoints are allowed only if current source supports this direction:

```text
routes/communication_group_notifications.py
services/group_notification_delivery_service.py
models/group_notification_receipt.py
```

## 13. Database / migration discipline

Track A requires a forward migration for shared Group Chat translation semantics.
Track C may require Group notification preference and/or delivery state.

Rules:

```text
historical_migrations_modified=NO
multiple_heads_created=NO
migration generated only after inspecting current head
upgrade and downgrade strategy documented
production data migration preserves encrypted translation values where valid
```

Do not merge unrelated schema work from PR #37.

## 14. Required tests — translation

Preserve and extend existing Group tests. At minimum prove:

```text
MESSAGE_WITH_NO_TRANSLATION_REQUEST_PROVIDER_CALLS=0
SHARED_VARIANT_IDENTITY=message+fingerprint+target
RECIPIENT_NOT_VARIANT_IDENTITY=PASS
REUSE_BEFORE_QUOTA=PASS
CONCURRENT_SAME_TARGET_PROVIDER_CALLS=1
CONCURRENT_SAME_TARGET_PAYER_COUNT=1
EXISTING_VARIANT_REUSE_COST=0
MESSAGE_EDIT_INVALIDATION=PASS
HISTORY_AUTO_TRANSLATE=NO
HISTORY_AUTO_READ=NO
ENCRYPTION_AT_REST=PASS
```

## 15. Required tests — notification UX

At minimum prove:

```text
SENDER_SELF_NOTIFICATION=0
SAME_GROUP_VISIBLE_NORMAL_MESSAGE_INTERNAL_ALERT=0
SAME_GROUP_VISIBLE_NORMAL_MESSAGE_WEB_PUSH=0
SMART_FIRST_UNREAD_NORMAL_ALERT=1
SMART_MESSAGE_BURST_ADDITIONAL_INTERRUPTIVE_ALERTS=0
SMART_UNREAD_BADGE_STILL_ADVANCES=PASS
AFTER_READ_NEXT_0_TO_1_ALERT_ALLOWED=PASS
DIRECT_REPLY_TARGETED_INTERNAL=PASS
STRUCTURED_MENTION_TARGETED=PASS_OR_DEFERRED_NO_REGEX
MODE_ALL_NORMAL_MESSAGE_ELIGIBLE=PASS
MODE_IMPORTANT_NORMAL_MESSAGE_SUPPRESSED=PASS
MODE_NONE_PUSH=0
MUTED_GROUP_PUSH=0
QUIET_HOURS_CHAT_WEB_PUSH=0
REMOVED_MEMBER_FUTURE_NOTIFICATION=0
RETRY_SAME_EVENT_LOGICAL_INTERNAL_ROWS=1
RETRY_SAME_EVENT_DUPLICATE_WEB_PUSH_WORK=0
TIMEBLOCK_DOWN_GROUP_MESSAGE_STILL_SUCCESS=PASS
RAW_MESSAGE_COPIED_TO_TIMEBLOCK=NO
RAW_TRANSLATION_COPIED_TO_TIMEBLOCK=NO
GROUP_EMAIL_ROWS_CREATED=0
GROUP_RESEND_CALLS=0
GROUP_SMTP_CALLS=0
```

## 16. Required tests — Call/Video/Radio notifications and ringtone

```text
CALL_INCOMING_INTERNAL=PASS
VIDEO_INCOMING_INTERNAL=PASS
CALL_INCOMING_WEB_PUSH_CONDITIONAL=PASS
VIDEO_INCOMING_WEB_PUSH_CONDITIONAL=PASS
CALL_FOREGROUND_RINGTONE=PASS
VIDEO_FOREGROUND_RINGTONE=PASS
CALL_RINGTONES_SINGLE_TAB_OWNER=PASS
VIDEO_RINGTONES_SINGLE_TAB_OWNER=PASS
RINGTONE_STOPS_ON_ALL_TERMINAL_STATES=PASS
CALLER_DOES_NOT_HEAR_INCOMING_RINGTONE=PASS
OUTGOING_RINGBACK_PRESERVED=PASS
RADIO_INVITE_INTERNAL=PASS
RADIO_PTT_BURST_NOTIFICATION=0
RADIO_CUSTOM_RINGTONE=0
```

## 17. Service Worker / mobile QA

Test at least:

```text
Desktop browser
390x844 mobile viewport
390x667 short mobile viewport
iPhone/Home Screen Web Push behavior remains OWNER MANUAL QA
```

Do not claim deterministic browser automation proves real iPhone Web Push or background custom ringtone.

## 18. Protected regression boundaries

Must remain passing:

```text
PR35_VIDEO_LATE_JOIN=PASS
PR35_RADIO_RAW_AUDIO=PASS
PR35_AUTO_READ_FIRST_USE=PASS
PR35_CALL_TRANSLATION=PASS
PR35_CALL_VIDEO_ROOM_PICKER=PASS
PR35_ACTIVE_ROOM_SWITCH=PASS
DIRECT_1_1_UNCHANGED=PASS
GROUP_CALL_VIDEO_RADIO_TRANSLATION_COST_POLICY_UNCHANGED=PASS
```

## 19. Workflow

Work continuously from lineage refresh through implementation. Do not request owner QA between phases.

Focused developer checks are allowed during implementation, but do not use GitHub Actions as owner QA.

Final discipline:

```text
refresh SAME PR #36 lineage from accepted main
-> inspect source in both repositories
-> update implementation plan only if source evidence requires it
-> implement complete bounded change
-> static completeness review
-> freeze exact candidate
-> run ONE final comprehensive local gate
-> push exact tested candidate to SAME PR #36
-> verify remote PR head == tested candidate
-> STOP
```

Do not merge main. Do not deploy Render. Do not start PR #37.

## 20. Final report schema

```text
STATUS=READY_FOR_OWNER_DEPLOY_QA|BLOCKED
TASK_ID=TB-GROUP-COLLAB-20260906-002
ACCEPTED_MAIN_SHA=1dd41308b4fda33797b3de3b09c5bc13efd0b720
CURRENT_MAIN_SHA=
CURRENT_PR36_HEAD_BEFORE_REFRESH=
LINEAGE_REFRESH_SHA=
PR_NUMBER=36
BRANCH=docs/group-chat-shared-variant-speaker-cost-20260906
FINAL_COMMIT_SHA=
REMOTE_PR_HEAD_SHA=
DEPLOY_TEST_SHA=

SHARED_CHAT_TRANSLATION=PASS|FAIL
CONCURRENT_SHARED_TRANSLATION_DEDUPE=PASS|FAIL
REQUESTER_FUNDED_ACCOUNTING=PASS|FAIL

GROUP_CHAT_SMART_NOTIFICATION=PASS|FAIL
SMART_FIRST_UNREAD_AGGREGATION=PASS|FAIL
SAME_SPACE_ACTIVE_SUPPRESSION=PASS|FAIL
REPLY_PRIORITY=PASS|FAIL
MENTION_POLICY=STRUCTURED_PASS|DEFERRED_NO_REGEX|FAIL
PER_GROUP_NOTIFICATION_MODES=PASS|FAIL
GROUP_PRESENCE=PASS|FAIL
TIMEBLOCK_S2S_NOTIFICATION_INGEST=PASS|FAIL
CROSS_SYSTEM_IDEMPOTENCY=PASS|FAIL
NOTIFICATION_FAILURE_NON_BLOCKING=PASS|FAIL
RAW_GROUP_CONTENT_COPIED_TO_TIMEBLOCK=NO|YES
GROUP_EMAIL=NO|YES
GROUP_RESEND=NO|YES
GROUP_SMTP=NO|YES

GROUP_CALL_RINGTONE_PARITY=PASS|FAIL
GROUP_VIDEO_RINGTONE_PARITY=PASS|FAIL
RINGTONE_MULTITAB_SINGLE_OWNER=PASS|FAIL
RINGTONE_TERMINAL_STOP=PASS|FAIL
GROUP_CALL_INTERNAL_PUSH=PASS|FAIL
GROUP_VIDEO_INTERNAL_PUSH=PASS|FAIL
GROUP_RADIO_INTERNAL_PUSH=PASS|FAIL
RADIO_PTT_PUSH=NO|YES

DATABASE_CHANGED=YES|NO
MIGRATION_CREATED=YES|NO
MIGRATION_HEADS=1|OTHER
TIMEBLOCK_CODE_CHANGED=YES|NO
AI_COMMUNICATION_CODE_CHANGED=YES|NO
DIRECT_1_1_CHANGED=NO|YES
ENV_CHANGED=YES|NO

JS_CHECK=
PYTHON_FOCUSED_TESTS=
BROWSER_TESTS=
MOBILE_390X844=
MOBILE_SHORT_VIEWPORT=
RENDER_CONTRACT=
SOURCE_LOCK=

OWNER_MANUAL_IPHONE_QA=PENDING
OWNER_MANUAL_WEB_PUSH_QA=PENDING
MERGED=NO
DEPLOYED=NO
PR37_STARTED=NO
READY_FOR_OWNER_DEPLOY_QA=YES|NO
```

If `READY_FOR_OWNER_DEPLOY_QA=YES`, provide exactly one `DEPLOY_TEST_SHA` and STOP.