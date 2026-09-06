# Group Translation Shared Variant Cost Contract v1.1

Status: **OWNER-APPROVED PRODUCT ARCHITECTURE UPDATE**
Decision date: **2026-09-06**
Applies to: **Group Chat, Group Call, Group Video, Group Radio translation** in `Panjiaphu/AI-COMMUNICATION-Timeblock`.

This v1.1 contract supersedes v1.0 only where Group Chat cost ownership and automatic translation policy are concerned. The approved Call/Video/Radio speaker-funded shared-variant model remains unchanged.

## 1. Core architecture shared by all Group translation

Translation text is shared by source unit/version and target language. It is **not** created separately for every recipient.

```text
SOURCE UNIT / SOURCE VERSION
  -> authoritative source text
  -> at most one FINAL variant per target language
  -> all authorized members needing that target language reuse the same variant
```

Global cost/reuse invariants:

```text
COST_UNIT=NEW_UNIQUE_TRANSLATION_VARIANT
SAME_LANGUAGE_TRANSLATION_COST=0
EXISTING_VARIANT_REUSE_COST=0
RECIPIENT_COUNT_MULTIPLIES_TRANSLATION_COST=NO
CONCURRENT_SAME_TARGET_PROVIDER_CALLS=1
TTS_PROVIDER_TRANSLATION_COST=0
AUDIO_PERSISTENCE=NONE
```

Cost ownership differs by source mode:

```text
CALL_VIDEO_RADIO_COST_OWNER=SOURCE_SPEAKER
GROUP_CHAT_COST_OWNER=FIRST_REQUESTER_WHO_CAUSES_MISSING_SHARED_VARIANT_CREATION
```

## 2. Call / Video / Radio policy — speaker-funded

For realtime voice media, the speaker who creates the source segment is the logical cost owner of any NEW provider translation variants created for that segment.

Example:

```text
A = vi
B,C = zh-TW
D,E = en

A speaks Vietnamese
-> source A/vi = authoritative, no translation call
-> A/zh-TW = create once; B,C reuse
-> A/en = create once; D,E reuse

MAX_NEW_PROVIDER_TRANSLATIONS=2
COST_OWNER=A
```

If B later speaks Traditional Chinese:

```text
source B/zh-TW = no translation call
B/vi = create once if required
B/en = create once if required
COST_OWNER=B
```

The number of recipients must never multiply provider translation calls when recipients share a target language.

### 2.1 Cost-minimum media target eligibility

To minimize provider cost without removing realtime translation for members who actually enabled it, target-language discovery should be demand-aware:

```text
ACTIVE/JOINED PARTICIPANTS
-> keep only participants who explicitly enabled/authorized translation for the current media session/profile
-> collect UNIQUE preferred target languages
-> remove source language
-> create only missing shared variants
```

Required optimization invariant:

```text
NO_TRANSLATION_ENABLED_RECIPIENTS -> NEW_PROVIDER_TRANSLATIONS=0
ONE_REQUIRED_TARGET_LANGUAGE -> MAX_NEW_PROVIDER_TRANSLATIONS=1
TWO_REQUIRED_TARGET_LANGUAGES -> MAX_NEW_PROVIDER_TRANSLATIONS=2
```

This is the cost-minimum target-selection direction. If an accepted production candidate still derives targets from every joined participant regardless of translation enablement, preserve that candidate for its current owner QA and implement this refinement in a separately sequenced media translation optimization task; do not silently expand an unrelated Group Chat migration.

## 3. Media history — source-first, shared reuse, speaker-funded missing variant

For historical Call/Video/Radio source segments:

```text
LOAD_SOURCE_HISTORY=YES
LATE_JOIN_HISTORY_AUTO_TRANSLATE=NO
LATE_JOIN_HISTORY_AUTO_READ=NO
HISTORY_TRANSLATE=ON_DEMAND
HISTORY_TTS=MANUAL_ON_DEMAND
```

When a late-joining member requests a target language:

```text
FINAL shared variant exists
-> reuse
-> provider calls added = 0
-> additional provider translation cost = 0

shared variant missing
-> create one missing target variant
-> COST_OWNER=ORIGINAL_SOURCE_SPEAKER
```

Example:

```text
source speaker=A
historical Translate requested by=F
missing media target variant required
COST_OWNER=A
REQUESTER_COST_OWNER=F -> NO
```

No fallback requester billing for another speaker's media history without a future owner decision.

## 4. Group Chat policy — requester-funded + shared + on-demand

Group Chat intentionally uses a different cost policy from voice media.

A text message is stored as source text first. Merely sending a message must not force automatic translation into every language present in the room.

Canonical policy:

```text
GROUP_CHAT_TRANSLATION_DEFAULT=ON_DEMAND
AUTO_TRANSLATE=USER_OPT_IN
NEW_SHARED_VARIANT_COST_OWNER=FIRST_SUCCESSFUL_REQUESTER
EXISTING_SHARED_VARIANT_REUSE_COST=0
HISTORY_REUSE_COST=0
```

The requester may be either the sender or a recipient. The determining rule is not sender/recipient role; it is who first causes a missing shared target-language variant to be created.

Example:

```text
A sends VI source message X
B,C target zh-TW
D,E target en

No user requests translation
-> provider calls=0
-> A cost=0

B first requests/auto-translates X -> zh-TW
-> shared zh-TW missing
-> provider call=1
-> COST_OWNER=B

C later needs zh-TW
-> reuse B-created FINAL variant
-> provider calls added=0
-> C cost=0

D first requests X -> en
-> shared en missing
-> provider call=1
-> COST_OWNER=D

E later needs en
-> reuse
-> provider calls added=0
-> E cost=0
```

If sender A explicitly requests an outgoing English translation before anyone else:

```text
A triggers missing X/en
-> COST_OWNER=A
-> later EN recipients reuse at zero new provider translation cost
```

## 5. Shared variant identity

### 5.1 Call / Video / Radio Translation V2

For immutable V2 media translation segments:

```text
(segment_id, target_language)
```

The current schema already enforces one `GroupTranslationVariant` per `segment_id + target_language`. Preserve that property.

### 5.2 Group Chat

For editable chat messages:

```text
(message_id, message_fingerprint, target_language)
```

`recipient_membership_id` must **not** be part of the shared translation-variant identity after the Group Chat migration.

If a message is edited:

```text
message_fingerprint changes
-> old variants are stale for the current message version
-> old translated text must not be projected as current
-> new variants are created only when a user actually requests/enables them
```

## 6. Group Chat request flow — reuse before quota

Every Chat translation request or opt-in Auto Translate event must perform reuse lookup before any requester quota reservation.

Required order:

```text
request target language
-> target == source?
   -> use source, cost=0
-> lookup shared (message_id, fingerprint, target_language)
-> FINAL exists?
   -> return/reuse immediately
   -> provider call=0
   -> requester quota check=NOT REQUIRED FOR PROVIDER WORK
-> missing?
   -> acquire canonical shared-variant lock/reservation
   -> recheck FINAL after lock
   -> reserve requester quota only if provider work is still required
   -> provider translation ONCE
   -> persist shared FINAL variant
   -> settle requester cost
```

A user with no remaining translation quota must still be allowed to reuse an authorized existing FINAL variant because reuse generates no new provider translation work.

## 7. Group Chat concurrency / payer selection

Two users can request the same missing target language simultaneously.

Required behavior:

```text
message X + fingerprint F + zh-TW
B request ----\
              -> canonical lock/reservation -> ONE provider call
C request ----/                              -> ONE stored FINAL variant
```

Payer rule:

```text
FIRST_SUCCESSFUL_RESERVATION_OWNER=COST_OWNER
LOSING_CONCURRENT_REQUESTERS=REUSE_AFTER_FINAL
DOUBLE_CHARGE=NO
```

Database uniqueness alone is insufficient if duplicate provider calls can happen before row conflict. Provider work must be coalesced before the external translation call.

Use a stable provider idempotency key derived from message-version + target language.

## 8. Group Chat history — reuse first, missing variant requester-funded

History remains source-first and on-demand.

Required:

```text
LOAD_SOURCE_HISTORY=YES
LATE_JOIN_HISTORY_AUTO_TRANSLATE=NO
LATE_JOIN_HISTORY_AUTO_READ=NO
HISTORY_TRANSLATE=ON_DEMAND
HISTORY_TTS=MANUAL_ON_DEMAND
```

For each historical message:

```text
recipient target == source
-> source already usable, cost=0

shared FINAL target variant exists
-> reuse, provider call=0, cost=0

shared target variant missing
-> show explicit Translate
-> first requester who causes creation becomes COST_OWNER
```

Example:

```text
A authored X/vi three days ago
B previously paid for X/zh-TW
F joins later and needs zh-TW
-> reuse X/zh-TW
-> F cost=0

G joins later and needs en
X/en missing
G presses Translate
-> provider call=1
-> COST_OWNER=G
-> all later EN users reuse at zero new provider cost
```

Manual historical Translate must not trigger Auto Read automatically.

## 9. Group Chat Auto Translate is authorization for missing provider work

Auto Translate should be user opt-in, not room-wide precomputation.

For user B:

```text
AUTO_TRANSLATE=ON
TARGET=zh-TW
```

For each new message:

```text
source == zh-TW
-> use source

source != zh-TW
-> lookup shared zh-TW variant first
   -> FINAL exists: reuse free
   -> missing: B is eligible to trigger one new provider translation and pay for it
```

If multiple same-target users have Auto Translate enabled, they still share one provider operation. The first successful canonical reservation owns the cost; later/concurrent users reuse.

Do not precompute translations merely because a room contains members with other preferred languages.

## 10. Provider failure / quota reservation

A requester should not be permanently charged merely for pressing Translate if provider work fails.

Target accounting flow:

```text
shared reuse lookup
-> missing only: requester quota eligibility
-> reserve bounded estimated usage
-> provider call
-> success: settle actual/approved usage
-> failure: release/expire reservation; no settled provider translation charge
```

Exact commercial billing units remain a dedicated quota/package task unless already defined by an approved schema.

## 11. TTS policy

Text translation variants are shared; TTS playback is local per device.

```text
shared translated text
  -> local browser/device TTS for member #1
  -> local browser/device TTS for member #2
```

Rules:

- do not create one server audio file per recipient;
- do not persist translation audio;
- realtime media Auto Read may speak eligible new realtime FINAL translations according to the user's setting;
- Chat Auto Translate does not imply server audio generation;
- history bootstrap must never Auto Read;
- historical TTS is explicit manual `Play on this device`;
- Manual Play and realtime Auto Read should share one deterministic local TTS manager.

## 12. Current-system migration rules

### Call / Video / Radio V2

The current `GroupTranslationVariant` model already has shared `(segment_id, target_language)` uniqueness. Preserve this behavior and speaker-funded cost ownership.

A separate media target-eligibility optimization may be required to ensure only translation-enabled active recipients contribute required target languages. Do not regress the already accepted shared-variant/history behavior while adding that refinement.

### Group Chat

Current Group Chat translation is recipient-scoped. Migrate it in the dedicated Group Chat task to:

```text
SHARED_IDENTITY=(message_id, message_fingerprint, target_language)
COST_OWNER=FIRST_REQUESTER_WHO_CREATES_MISSING_VARIANT
TRANSLATION_DEFAULT=ON_DEMAND
AUTO_TRANSLATE=USER_OPT_IN
```

Preserve:

- message edit/fingerprint invalidation;
- encryption-at-rest;
- authorization/membership boundaries;
- consent/profile behavior;
- stable idempotency;
- current message source-language truth;
- room event invalidation;
- no Direct 1:1 ownership/runtime change.

## 13. Required tests

### Media/Radio shared-cost tests

```text
ROOM:
vi x1
zh-TW x2
en x2

VI speaker creates eligible realtime source segment
EXPECTED unique target variants <= {zh-TW,en}
EXPECTED provider calls <= 2
EXPECTED recipient-count multiplier=NO
EXPECTED cost owner=speaker
```

Media history:

```text
late join
-> source history visible
-> existing target variant reused at zero new provider cost
-> no automatic historical translation
-> no automatic historical TTS
-> missing media historical variant remains speaker-funded
```

### Group Chat tests

```text
MESSAGE_CREATED_WITH_NO_TRANSLATION_REQUEST -> PROVIDER_CALLS=0
SHARED_VARIANT_IDENTITY=message_id+fingerprint+target_language
RECIPIENT_ID_NOT_VARIANT_IDENTITY=YES
SAME_LANGUAGE_SOURCE_REUSE=PASS
FIRST_REQUESTER_MISSING_TARGET_IS_COST_OWNER=PASS
EXISTING_VARIANT_REUSE_PROVIDER_CALLS_ADDED=0
EXISTING_VARIANT_REUSE_REQUIRES_NEW_REQUESTER_QUOTA=NO
CONCURRENT_SAME_TARGET_PROVIDER_CALLS=1
CONCURRENT_LOSER_ADDITIONAL_COST=0
AUTO_TRANSLATE_OPT_IN_ONLY=PASS
ROOM_MEMBER_LANGUAGE_ALONE_DOES_NOT_PRECOMPUTE_VARIANT=PASS
MESSAGE_EDIT_INVALIDATES_OLD_VARIANT=PASS
HISTORY_SOURCE_VISIBLE=PASS
HISTORY_AUTO_TRANSLATE=NO
HISTORY_AUTO_READ=NO
HISTORY_EXISTING_VARIANT_REUSE_COST=0
HISTORY_MISSING_VARIANT_COST_OWNER=REQUESTER
HISTORY_MANUAL_TTS=PASS
AUDIO_PERSISTENCE=NONE
```

## 14. Protected boundaries

This contract does not authorize:

- Direct 1:1 ownership/runtime changes;
- translation-owned second microphone acquisition;
- LiveKit/Cloudflare media ownership changes;
- audio archive/storage;
- server TTS audio generation per recipient;
- recipient-specific duplicate Chat translations;
- room-wide Chat translation precomputation merely from member language profiles;
- charging a requester for reuse of an existing FINAL shared Chat variant;
- changing accepted PR #35 production code inside the docs-only Group Chat planning branch.
