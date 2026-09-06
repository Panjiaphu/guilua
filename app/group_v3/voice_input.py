"""Bounded memory-only multipart input. Never spool a voice clip to disk."""
from email import policy
from email.parser import BytesParser

from fastapi import HTTPException, Request


async def read_voice_form(request: Request) -> tuple[dict, bytes, str, str]:
    maximum = request.app.state.settings.group_translation_max_audio_bytes
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data;"):
        raise HTTPException(400, "group_translation_audio_invalid")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum + 16384:
            raise HTTPException(413, "group_translation_audio_invalid")
        body.extend(chunk)
    message = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + body
    )
    body.clear()
    if not message.is_multipart() or message.defects:
        raise HTTPException(400, "group_translation_audio_invalid")
    fields, audio, filename, mime = {}, None, "", ""
    for index, part in enumerate(message.iter_parts()):
        name = part.get_param("name", header="content-disposition")
        if index > 8 or not name or name in fields or part.is_multipart():
            raise HTTPException(400, "invalid_translation_segment")
        data = part.get_payload(decode=True) or b""
        if name == "audio":
            if audio is not None or not data or len(data) > maximum:
                raise HTTPException(413, "group_translation_audio_invalid")
            audio, filename, mime = data, part.get_filename() or "voice", part.get_content_type()
        else:
            if len(data) > 1024:
                raise HTTPException(400, "invalid_translation_segment")
            try:
                fields[name] = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HTTPException(400, "invalid_translation_segment") from exc
    if audio is None or not mime.startswith("audio/"):
        raise HTTPException(400, "group_translation_audio_invalid")
    return fields, audio, filename[:120], mime
