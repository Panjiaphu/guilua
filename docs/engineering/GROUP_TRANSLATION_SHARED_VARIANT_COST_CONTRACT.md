# Group Translation Shared Variant + Speaker-Funded Cost Contract v1.0

Status: **OWNER-APPROVED PRODUCT ARCHITECTURE**
Decision date: **2026-09-06**
Applies to: **Group Chat, Group Call, Group Video, Group Radio translation** in `Panjiaphu/AI-COMMUNICATION-Timeblock`.

This contract defines translation reuse, history behavior, TTS behavior, and logical cost ownership. It must be preserved by Group translation work unless the owner explicitly replaces it with a newer contract.

## 1. Core architecture

Translation is shared by source unit and target language. It is **not** created separately for every recipient.

```text
SOURCE UNIT
  -> authoritative source text
  -> one target-language variant per required language
  -> all authorized members with that target language reuse the same variant
```

Canonical cost/reuse rules:

```text
COST_UNIT=NEW_UNIQUE_TRANSLATION_VARIANT
COST_OWNER=SOURCE_AUTHOR_OR_SPEAKER
SAME_LANGUAGE_TRANSLATION_COST=0
EXISTING_VARIANT_REUSE_COST=0
RECIPIENT_COUNT_MULTIPLIES_TRANSLATION_COST=NO
HISTORY_REQUESTER_BECOMES_COST_OWNER=NO
TTS_PROVIDER_TRANSLATION_COST=0
AUDIO_PERSISTENCE=NONE
```

A member who creates/speaks the source content is the logical cost owner for any new provider translation work generated from that source unit. A recipient may trigger a missing historical variant, but the recipient does not become the cost owner.

## 2. Example: five-member room

```text
A = vi
B = zh-TW
C = zh-TW
D = en
E = en
```

If A speaks Vietnamese:

```text
source A/vi = authoritative source; no translation request
A/zh-TW = create once; B and C reuse
A/en = create once; D and E reuse
```

Required result:

```text
PARTICIPANTS=5
UNIQUE_LANGUAGES=3
SOURCE_LANGUAGE=vi
MAX_NEW_PROVIDER_TRANSLATIONS=2
COST_OWNER=A
```

If B later speaks Traditional Chinese:

```text
source B/zh-TW = no translation request
B/vi = create once; A reuses
B/en = create once; D and E reuse
COST_OWNER=B
```

The number of recipients must never multiply provider translation calls when recipients share a target language.

## 3. Shared variant identity

### 3.1 Call / Video / Radio Translation V2

For immutable V2 translation segments, the current semantic identity is:

```text
(segment_id, target_language)
```

The current schema already enforces one `GroupTranslationVariant` per `segment_id + target_language`. Preserve that property.

### 3.2 Group Chat

For editable chat messages, the semantic identity is:

```text
(message_id, message_fingerprint, target_language)
```

`recipient_membership_id` must **not** be part of the shared translation-variant identity after the Group Chat migration.

If a message is edited and its fingerprint changes, old variants are stale and must not be reused for the new message version.

## 4. Concurrency / idempotency

Two recipients requesting the same missing language variant concurrently must not create two provider translations.

Required behavior:

```text
request #1: source X -> zh-TW
request #2: source X -> zh-TW
        |
        v
coalesce / lock / authoritative uniqueness
        |
        v
ONE provider translation operation
ONE stored FINAL variant
both authorized clients reuse the same result
```

A database uniqueness constraint alone is insufficient if provider calls can occur before the conflict is detected. The implementation must prevent duplicate provider calls, not merely duplicate stored rows.

Provider idempotency keys should be stable for the shared source-version + target language.

## 5. Realtime translation policy

For an eligible new realtime source unit:

```text
source language resolved
-> collect UNIQUE active target languages
-> remove source language
-> check existing variant for each target
-> create only missing unique variants
-> cost attribution remains with source author/speaker
-> recipients reuse matching finalized variant
```

Example with 100 participants but only `vi`, `zh-TW`, `en`:

```text
speaker=vi
60 zh-TW recipients
30 en recipients
10 vi recipients

provider translations:
vi -> zh-TW : once
vi -> en    : once
```

## 6. Historical translation on demand

History is intentionally cheaper than realtime translation.

For history that existed before a member joined or before they requested translation:

```text
LOAD_SOURCE_HISTORY=YES
LATE_JOIN_HISTORY_AUTO_TRANSLATE=NO
LATE_JOIN_HISTORY_AUTO_READ=NO
HISTORY_TRANSLATE=ON_DEMAND
HISTORY_TTS=MANUAL_ON_DEMAND
```

Authorized members must always be able to see the source text/history permitted by the room.

When a member presses `Translate` on one historical item:

```text
lookup shared variant for their target language
|
+-- FINAL exists -> reuse; provider calls added = 0
|
+-- absent/failed retry-eligible -> create one shared missing variant
```

A manually requested historical translation must not automatically speak merely because Auto Read is enabled.

## 7. Historical cost ownership

If member B requests a missing `zh-TW` historical variant for content authored by A:

```text
REQUESTED_BY=B
COST_OWNER=A
```

B must not be silently charged for A's historical content.

If the original author's applicable translation quota is exhausted or the cost owner cannot authorize new provider work:

```text
existing FINAL variant -> reuse normally at zero new translation cost
missing variant -> do not silently charge requester; return a truthful quota/unavailable state
```

No fallback requester billing is allowed without a future explicit owner decision.

## 8. TTS policy

Text translation variants are shared; TTS playback is local per device.

```text
shared translated text
  -> local browser/device TTS for member #1
  -> local browser/device TTS for member #2
```

Rules:

- do not create one server audio file per recipient;
- do not persist translation audio;
- realtime Auto Read may speak eligible **new** realtime FINAL translations according to the user's local/room profile setting;
- history bootstrap must never Auto Read;
- historical TTS is explicit manual `Play on this device`;
- Manual Play and realtime Auto Read should share one deterministic local TTS manager.

## 9. Package/quota boundary

This document locks **logical cost ownership** and translation deduplication. It does not authorize inventing a new billing unit inside an unrelated corrective task.

Current Group media quota structures are target-seconds based. If the product package later requires token-denominated quota accounting, implement it in a dedicated quota/billing task with explicit schema/config/accounting acceptance criteria.

Until that task exists, Group translation code must at minimum preserve:

```text
provider work attributed to source author/speaker context
one provider call per missing unique target-language variant
zero new provider call for reuse
no recipient-count multiplier
```

## 10. Current-system migration rule

### Call / Video / Radio V2

The current `GroupTranslationVariant` model already has shared `(segment_id, target_language)` uniqueness. Corrective work must preserve and test this behavior, and must not regress to recipient-specific translation variants.

### Group Chat

The current Group Chat translation model/service is recipient-scoped. It must be migrated in a dedicated Group Chat task to the shared-variant model defined here.

That migration must preserve:

- message edit/fingerprint invalidation;
- encryption-at-rest;
- authorization/membership boundaries;
- consent/profile behavior;
- idempotency;
- current message source-language truth;
- current room event invalidation;
- no Direct 1:1 migration or ownership change.

## 11. Required tests for shared translation semantics

At minimum, implementation tests must prove:

```text
ROOM:
vi x1
zh-TW x2
en x2

VI source unit created
EXPECTED NEW TARGET VARIANTS:
zh-TW x1
en x1
EXPECTED PROVIDER TRANSLATION CALLS=2
```

Concurrent historical request test:

```text
ZH member #1 requests X/zh-TW
ZH member #2 requests X/zh-TW concurrently

EXPECTED:
provider calls=1
stored shared variants=1
both users receive same translated text
```

Reuse test:

```text
third zh-TW member later requests X/zh-TW
EXPECTED additional provider calls=0
```

History test:

```text
late join
-> source history visible
-> no automatic historical translation
-> no automatic historical TTS
-> explicit Translate reuses existing shared variant or creates one missing shared variant
-> explicit Play uses local TTS
```

Cost-owner test:

```text
source author=A
historical translate requested by=B
new provider variant required
EXPECTED logical cost owner=A
EXPECTED requester cost owner=B -> NO
```

## 12. Protected boundaries

This contract does not authorize:

- Direct 1:1 ownership/runtime changes;
- translation-owned second microphone acquisition;
- LiveKit ownership rewrites;
- audio archive/storage;
- server TTS audio generation per recipient;
- recipient-based duplicate translations;
- silent requester billing for another member's historical source content.
