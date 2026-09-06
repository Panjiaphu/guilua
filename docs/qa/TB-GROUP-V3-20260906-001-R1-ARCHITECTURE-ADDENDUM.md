# TB-GROUP-V3-20260906-001-R1 — Architecture Addendum

Status: **OWNER-APPROVED / BINDING FOR R1**
Date: **2026-09-06**
Parent task: `docs/qa/TB-GROUP-V3-20260906-001-R1.md`
Architecture authority: `docs/engineering/GROUP_TRANSLATION_SHARED_VARIANT_COST_CONTRACT.md`

## Purpose

This addendum locks the owner-approved shared-translation architecture while PR #35 executes the existing R1 corrective scope. It prevents R1 fixes from introducing recipient-specific translation duplication or history Auto Read behavior that conflicts with the product decision.

## Binding invariants for R1

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

For Call / Video / Radio Translation V2, preserve current shared variant semantics:

```text
UNIQUE(segment_id, target_language)
```

Do not replace this with recipient-scoped variants.

For five participants `vi x1`, `zh-TW x2`, `en x2`, one Vietnamese source segment must require at most two unique target variants (`zh-TW`, `en`), never one provider translation per recipient.

## Realtime vs history behavior

R1 Auto Read fixes must preserve this boundary:

```text
NEW REALTIME ELIGIBLE FINAL TRANSLATION
-> may Auto Read according to recipient setting

HISTORY / BOOTSTRAP
-> must not enqueue automatic TTS merely because Auto Read is enabled
```

Historical source text remains authoritative. Product architecture for historical missing variants is on-demand/shared reuse, not automatic translation of an entire late-join backlog.

If R1 touches historical projection, it must not introduce automatic translation or automatic playback of all historical items.

## R1 scope protection

This addendum does **not** authorize R1 to expand into a new billing migration or the dedicated Group Chat shared-variant migration.

Do not add in PR #35 solely because of this addendum:

```text
new token-denominated package accounting
requester billing
per-recipient translation variants
server TTS audio
Group Chat recipient-scope migration
unrelated quota schema redesign
```

The dedicated Group Chat migration is planned separately under:

```text
docs/qa/TB-GROUP-CHAT-20260906-001.md
```

and must execute only after exact continuation lineage is resolved following R1.

## Additional R1 regression invariant

R1 must retain/add a focused assertion proving shared media translation semantics are not regressed:

```text
ROOM: vi x1, zh-TW x2, en x2
SOURCE=vi
UNIQUE_TARGETS={zh-TW,en}
EXPECTED_VARIANTS=2
RECIPIENT_COUNT=5
RECIPIENT_SPECIFIC_PROVIDER_MULTIPLIER=NO
```

If the current implementation already satisfies this, preserve it rather than redesigning it.
