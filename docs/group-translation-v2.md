# Group Translation V2

Group Video and Group Radio translation use a text-first pipeline owned by
AI-COMMUNICATION. A participant submits text or explicitly records one clip
from the already-connected microphone. The server stores one encrypted
canonical source segment, calls STT once for voice input, and translates once
per distinct recipient language. The API projects only the current recipient's
preferred language; other variants are never returned to that participant.

`PROCESSING`, `FINAL`, `PARTIAL`, and `FAILED` are persisted on the segment and
variant rows. A failed variant can be retried without repeating STT or creating
another source segment. Durable events contain only a space and resource ID;
clients re-read authorized history. Final text is visible before optional
recipient-local `speechSynthesis`; automatic reading is off by default.

Every joined member participates in routing even before saving a
`GroupLanguageProfile`. The effective-profile fallback uses the canonical
source language for that segment, so the member receives the original-language
projection and is counted in the Author View. A stored profile takes precedence
as soon as it is saved. The browser Translation controller is the only profile
writer and synchronizes the shared Group runtime profile after a successful
PUT; failures remain visible to the user.

Auto Read is recipient-owned: a new FINAL segment is played once only on a
recipient device with Auto Read enabled, never on the speaker's own device.
Playback is local browser `speechSynthesis` because no Group-owned TTS endpoint
is part of the current schema; this is an explicit fallback and is never
published into LiveKit or Radio/PTT. History/SSE/rerender/reconnect and layout
changes use a runtime/segment/language/state dedupe key.

The normal Group V3 path does not capture remote audio, publish PTT audio to a
translation service, create a browser provider session, or request a second
microphone. Legacy reservation endpoints remain for compatibility but are not
called by the V2 client.

Endpoints:

- `POST /api/group/spaces/{space}/translation/segments/text`
- `POST /api/group/spaces/{space}/translation/segments/voice`
- `POST /api/group/spaces/{space}/translation/segments/{segment}/variants/{target}/retry`
- `GET /api/group/spaces/{space}/translation/v2-history`
