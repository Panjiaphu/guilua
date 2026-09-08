from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx

from app.communication.schemas import AuthorizedSession
from app.core.config import Settings
from app.handoff.group import GroupHandoff, parse_group_handoff
from app.handoff.group_media import (
    GroupMediaProviderContract,
    GroupMediaSession,
    parse_group_media_provider_contract,
    parse_group_media_session,
)


class TimeblockIntegrationError(RuntimeError):
    pass


class TimeblockRequestTooLarge(TimeblockIntegrationError):
    pass


@dataclass(slots=True)
class TimeblockProxyResponse:
    status_code: int
    headers: dict[str, str]
    body: AsyncIterator[bytes]


_SAFE_PROXY_RESPONSE_HEADERS = {
    'accept-ranges',
    'cache-control',
    'content-disposition',
    'content-encoding',
    'content-length',
    'content-range',
    'content-type',
    'etag',
    'expires',
    'last-modified',
    'pragma',
    'retry-after',
    'x-content-type-options',
    'x-request-id',
    'x-timeblock-call-id',
    'x-timeblock-provider-code',
    'x-timeblock-speech-model',
    'x-timeblock-translation-request-id',
    'x-timeblock-translation-segment-id',
    'x-timeblock-usage',
}
_SAFE_PROXY_REQUEST_HEADERS = {
    'idempotency-key',
    'last-event-id',
    'user-agent',
    'x-timeblock-call-v1-request-id',
}
_SAFE_PROXY_METHODS = {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}


@dataclass(slots=True)
class TimeblockClient:
    settings: Settings
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)

    def _pooled_client(self) -> httpx.AsyncClient:
        """Reuse one connection pool for non-streaming control-plane calls."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.settings.timeblock_timeout_seconds,
                follow_redirects=False,
            )
        return self._client

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None and not client.is_closed:
            await client.aclose()

    def _api_url(self, path: str) -> str:
        if not self.settings.timeblock_api_url or not self.settings.timeblock_api_key:
            raise TimeblockIntegrationError('timeblock_not_configured')
        if not path.startswith('/') or '?' in path or '#' in path:
            raise TimeblockIntegrationError('timeblock_invalid_path')
        return f"{self.settings.timeblock_api_url.rstrip('/')}{path}"

    def _server_headers(self, *, client_session: str | None = None) -> dict[str, str]:
        if not self.settings.timeblock_api_key:
            raise TimeblockIntegrationError('timeblock_not_configured')
        headers = {'Authorization': f'Bearer {self.settings.timeblock_api_key}'}
        if client_session:
            headers['X-Timeblock-Client-Session'] = client_session
        return headers

    @staticmethod
    def _safe_proxy_response_headers(headers: httpx.Headers) -> dict[str, str]:
        return {
            name: value
            for name, value in headers.items()
            if name.lower() in _SAFE_PROXY_RESPONSE_HEADERS
        }

    @staticmethod
    async def _bounded_body(
        body: AsyncIterable[bytes],
        maximum_bytes: int,
    ) -> AsyncIterator[bytes]:
        total = 0
        async for chunk in body:
            if not chunk:
                continue
            total += len(chunk)
            if total > maximum_bytes:
                raise TimeblockRequestTooLarge('request_too_large')
            yield chunk

    async def proxy_request(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: Sequence[tuple[str, str]] = (),
        body: AsyncIterable[bytes] | None = None,
        content_type: str = '',
        forwarded_headers: Mapping[str, str] | None = None,
        maximum_body_bytes: int,
        stream_response: bool = False,
    ) -> TimeblockProxyResponse:
        """Forward one allowlisted BFF request without exposing server credentials.

        Route allowlisting and browser-origin checks live in ``app.bff.proxy``.
        This transport intentionally never forwards browser cookies,
        authorization, CORS, or arbitrary headers.
        """

        normalized_method = method.upper()
        if normalized_method not in _SAFE_PROXY_METHODS:
            raise TimeblockIntegrationError('timeblock_invalid_method')
        if maximum_body_bytes <= 0:
            raise TimeblockIntegrationError('timeblock_invalid_body_limit')

        headers = self._server_headers(client_session=token)
        if content_type:
            headers['Content-Type'] = content_type
        for name, value in (forwarded_headers or {}).items():
            if name.lower() in _SAFE_PROXY_REQUEST_HEADERS and value:
                headers[name] = value

        timeout: httpx.Timeout
        if stream_response:
            timeout = httpx.Timeout(
                self.settings.timeblock_timeout_seconds,
                read=None,
                write=self.settings.timeblock_proxy_timeout_seconds,
            )
        else:
            timeout = httpx.Timeout(
                self.settings.timeblock_timeout_seconds,
                read=self.settings.timeblock_proxy_timeout_seconds,
                write=self.settings.timeblock_proxy_timeout_seconds,
            )

        client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        request_body = (
            self._bounded_body(body, maximum_body_bytes)
            if body is not None
            else None
        )
        try:
            upstream_request = client.build_request(
                normalized_method,
                self._api_url(path),
                params=list(params),
                headers=headers,
                content=request_body,
            )
            upstream_response = await client.send(upstream_request, stream=True)
        except TimeblockRequestTooLarge:
            await client.aclose()
            raise
        except httpx.HTTPError as exc:
            await client.aclose()
            raise TimeblockIntegrationError('timeblock_request_failed') from exc
        except Exception:
            await client.aclose()
            raise

        async def response_body() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream_response.aiter_raw():
                    yield chunk
            finally:
                await upstream_response.aclose()
                await client.aclose()

        return TimeblockProxyResponse(
            status_code=upstream_response.status_code,
            headers=self._safe_proxy_response_headers(upstream_response.headers),
            body=response_body(),
        )

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        client_session: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict:
        headers = self._server_headers(client_session=client_session)
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        try:
            response = await self._pooled_client().post(
                self._api_url(path),
                headers=headers,
                json=payload,
                timeout=(
                    timeout_seconds
                    if timeout_seconds is not None
                    else self.settings.timeblock_timeout_seconds
                ),
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TimeblockIntegrationError('timeblock_request_failed') from exc
        try:
            data = response.json() if response.content else {}
        except ValueError as exc:
            raise TimeblockIntegrationError('timeblock_invalid_response') from exc
        if not isinstance(data, dict):
            raise TimeblockIntegrationError('timeblock_invalid_response')
        return data

    async def _get(self, path: str, *, client_session: str, params: dict[str, Any] | None = None) -> dict:
        headers = self._server_headers(client_session=client_session)
        try:
            response = await self._pooled_client().get(
                self._api_url(path),
                headers=headers,
                params=params or {},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TimeblockIntegrationError('timeblock_request_failed') from exc
        try:
            data = response.json() if response.content else {}
        except ValueError as exc:
            raise TimeblockIntegrationError('timeblock_invalid_response') from exc
        if not isinstance(data, dict):
            raise TimeblockIntegrationError('timeblock_invalid_response')
        return data

    async def contract_capabilities(self) -> dict:
        try:
            response = await self._pooled_client().get(
                self._api_url('/api/guilua/v2/capabilities'),
                headers=self._server_headers(),
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TimeblockIntegrationError('timeblock_contract_unavailable') from exc
        try:
            data = response.json() if response.content else {}
        except ValueError as exc:
            raise TimeblockIntegrationError('timeblock_invalid_response') from exc
        if (
            not isinstance(data, dict)
            or str(data.get('contract_version') or '') != '2'
            or str(data.get('authority') or '') != 'timeblock'
            or not isinstance(data.get('capabilities'), list)
        ):
            raise TimeblockIntegrationError('timeblock_contract_mismatch')
        return data

    async def ingest_group_notification(
        self,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict:
        """Send one trusted metadata-only Group delivery to Timeblock."""
        return await self._post(
            "/api/communication/group/notifications/ingest",
            payload,
            idempotency_key=idempotency_key,
            timeout_seconds=max(self.settings.timeblock_timeout_seconds, 35.0),
        )

    async def redeem_group_handoff_v3(
        self,
        handoff_code: str,
        *,
        source_origin: str,
        target_origin: str,
        audience: str,
    ) -> dict:
        return await self._post(
            '/api/communication/group/handoffs/redeem',
            {
                'handoff_code': handoff_code,
                'source_origin': source_origin,
                'target_origin': target_origin,
                'audience': audience,
            },
        )

    @staticmethod
    def parse_group_handoff(payload: Mapping[str, object]) -> GroupHandoff:
        """Validate a browser-delivered Group Contract V2 envelope in memory."""

        try:
            return parse_group_handoff(payload)
        except ValueError as exc:
            raise TimeblockIntegrationError('timeblock_group_handoff_invalid') from exc

    @staticmethod
    def parse_group_media_provider_contract(
        payload: Mapping[str, object],
    ) -> GroupMediaProviderContract:
        """Validate provider readiness before any future media setup."""

        try:
            return parse_group_media_provider_contract(payload)
        except ValueError as exc:
            raise TimeblockIntegrationError(
                'timeblock_group_media_provider_contract_invalid'
            ) from exc

    @staticmethod
    def parse_group_media_session(payload: Mapping[str, object]) -> GroupMediaSession:
        """Validate an ephemeral provider grant before passing it to media code."""

        try:
            return parse_group_media_session(payload)
        except ValueError as exc:
            raise TimeblockIntegrationError(
                'timeblock_group_media_session_invalid'
            ) from exc

    async def exchange_guilua_code(self, code: str, redirect_uri: str) -> dict:
        return await self._post(
            '/api/guilua/token',
            {
                'grant_type': 'authorization_code',
                'client_id': self.settings.guilua_client_id,
                'code': code,
                'redirect_uri': redirect_uri,
            },
        )

    async def refresh_guilua_session(self, token: str) -> dict:
        return await self._post(
            '/api/guilua/token/refresh',
            {'client_id': self.settings.guilua_client_id, 'session_token': token},
        )

    async def revoke_guilua_session(self, token: str) -> None:
        await self._post(
            '/api/guilua/session/revoke',
            {'client_id': self.settings.guilua_client_id, 'session_token': token},
        )

    async def client_get(self, path: str, token: str, *, params: dict[str, Any] | None = None) -> dict:
        return await self._get(path, client_session=token, params=params)

    async def client_post(self, path: str, token: str, payload: dict[str, Any]) -> dict:
        return await self._post(path, payload, client_session=token)

    @staticmethod
    def _bind_authorized_session(
        data: dict,
        session_id: str,
        participant_id: str,
        workspace_id: str | None = None,
    ) -> AuthorizedSession:
        try:
            authorized = AuthorizedSession.model_validate(data)
        except Exception as exc:
            raise TimeblockIntegrationError('timeblock_invalid_response') from exc
        if authorized.session_id != session_id or authorized.participant_id != participant_id:
            raise TimeblockIntegrationError('authorization_boundary_mismatch')
        if workspace_id is not None and authorized.workspace_id != workspace_id:
            raise TimeblockIntegrationError('authorization_boundary_mismatch')
        return authorized

    @staticmethod
    def _authorization_payload(
        participant_id: str,
        session_token: str,
        *,
        workspace_id: str | None = None,
        issuer: str | None = None,
        audience: str | None = None,
    ) -> dict[str, str]:
        payload = {'participant_id': participant_id, 'session_token': session_token}
        if workspace_id:
            payload['workspace_id'] = workspace_id
        if issuer:
            payload['issuer'] = issuer
        if audience:
            payload['audience'] = audience
        return payload

    async def authorize_session(
        self,
        session_id: str,
        session_token: str,
        participant_id: str,
        *,
        workspace_id: str | None = None,
        issuer: str | None = None,
        audience: str | None = None,
    ) -> AuthorizedSession:
        if self.settings.development_session_fallback_enabled:
            if session_token != 'development-session':
                raise TimeblockIntegrationError('invalid_development_session')
            return AuthorizedSession(
                session_id=session_id,
                room_id=f'room-{session_id}',
                workspace_id=workspace_id or 'development',
                participant_id=participant_id,
            )
        data = await self._post(
            f'/api/communication/sessions/{session_id}/authorize',
            self._authorization_payload(
                participant_id,
                session_token,
                workspace_id=workspace_id,
                issuer=issuer,
                audience=audience,
            ),
        )
        return self._bind_authorized_session(data, session_id, participant_id, workspace_id)

    async def refresh_session(
        self,
        session_id: str,
        session_token: str,
        participant_id: str,
        *,
        workspace_id: str | None = None,
        issuer: str | None = None,
        audience: str | None = None,
    ) -> AuthorizedSession:
        if self.settings.development_session_fallback_enabled:
            return await self.authorize_session(
                session_id,
                session_token,
                participant_id,
                workspace_id=workspace_id,
                issuer=issuer,
                audience=audience,
            )
        data = await self._post(
            f'/api/communication/sessions/{session_id}/refresh',
            self._authorization_payload(
                participant_id,
                session_token,
                workspace_id=workspace_id,
                issuer=issuer,
                audience=audience,
            ),
        )
        return self._bind_authorized_session(data, session_id, participant_id, workspace_id)

    async def fetch_glossary(self, workspace_id: str, version: str | None = None) -> dict:
        return await self._post('/api/communication/glossary', {'workspace_id': workspace_id, 'version': version})

    async def submit_session_result(self, payload: dict, idempotency_key: str | None = None) -> None:
        if self.settings.development_session_fallback_enabled:
            return
        await self._post(
            '/api/communication/session-results',
            payload,
            idempotency_key=idempotency_key or str(uuid4()),
        )

    async def submit_usage(self, events: list[dict], idempotency_key: str | None = None) -> None:
        if self.settings.development_session_fallback_enabled:
            return
        await self._post(
            '/api/communication/usage',
            {'events': events},
            idempotency_key=idempotency_key or str(uuid4()),
        )
