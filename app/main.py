from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.communication.manager import RoomManager
from app.communication.router import router as communication_router
from app.group_translation.provider import OpenAIGroupTranslationProvider
from app.group_v3.crypto import GroupCrypto
from app.group_v3.chat_translation_service import GroupChatTranslationService
from app.group_v3.events import GroupEventBroker
from app.group_v3.media import LiveKitGroupMediaProvider
from app.group_v3.invitation_service import GroupInvitationService
from app.group_v3.radio_floor import DistributedRadioFloor
from app.group_v3.radio_router import router as group_v3_radio_router
from app.group_v3.radio_service import GroupRadioService
from app.group_v3.router import router as group_v3_router
from app.group_v3.session_router import router as group_v3_session_router
from app.group_v3.session_service import GroupMediaSessionService
from app.group_v3.translation_router import router as group_v3_translation_router
from app.group_v3.translation_service import GroupTranslationService
from app.group_v3.service import GroupService, GroupServiceError
from app.handoff.router_v3 import router as group_handoff_v3_router
from app.bff.router import router as bff_router
from app.bff.session_store import SessionStore
from app.core.config import BASE_DIR, Settings, get_settings
from app.db import Database, GROUP_V3_SCHEMA_REVISION
from app.integrations.timeblock.client import TimeblockClient, TimeblockIntegrationError
from app.telemetry.logging import configure_logging

configure_logging()


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def cleanup_loop() -> None:
            while True:
                await asyncio.sleep(30)
                await app.state.room_manager.cleanup()
                drain_outbox = getattr(app.state.group_event_broker, "drain_outbox", None)
                if drain_outbox:
                    await drain_outbox()
                if app.state.settings.group_radio_v3_enabled:
                    try:
                        await app.state.group_radio_service.reconcile_device_loss(app.state.group_radio_floor)
                    except GroupServiceError:
                        pass
                if app.state.settings.group_translation_enabled:
                    try:
                        app.state.group_translation_service.reconcile_expired()
                    except GroupServiceError:
                        pass

        task = asyncio.create_task(cleanup_loop())
        try:
            start_events = getattr(application.state.group_event_broker, "start", None)
            if start_events:
                await start_events()
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            close_client = getattr(getattr(app, "state", None), "timeblock_client", None)
            close_method = getattr(close_client, "aclose", None)
            if close_method:
                await close_method()
            database = getattr(getattr(app, "state", None), "database", None)
            if database:
                database.dispose()
            group_radio_floor = getattr(getattr(app, "state", None), "group_radio_floor", None)
            if group_radio_floor:
                await group_radio_floor.close()
            group_event_broker = getattr(getattr(app, "state", None), "group_event_broker", None)
            close_events = getattr(group_event_broker, "close", None)
            if close_events:
                await close_events()

    application = FastAPI(title=runtime_settings.app_name, debug=runtime_settings.debug, lifespan=lifespan)
    application.state.settings = runtime_settings
    application.state.database = Database(runtime_settings)
    group_crypto = GroupCrypto(runtime_settings)
    livekit_provider = LiveKitGroupMediaProvider(runtime_settings)
    application.state.group_media_provider = livekit_provider
    application.state.group_event_broker = GroupEventBroker(
        database=application.state.database,
        redis_url=runtime_settings.group_radio_redis_url,
        redis_namespace=f"{runtime_settings.group_radio_redis_namespace}:group-events",
    )
    application.state.group_service = GroupService(
        application.state.database, group_crypto, application.state.group_event_broker
    )
    application.state.group_invitation_service = GroupInvitationService(
        application.state.database,
        runtime_settings.group_invitation_ttl_seconds,
        application.state.group_event_broker,
    )
    application.state.group_media_session_service = GroupMediaSessionService(
        application.state.database,
        runtime_settings,
        livekit_provider,
        application.state.group_event_broker,
    )
    openai_translation_provider = OpenAIGroupTranslationProvider(runtime_settings)
    application.state.openai_group_translation_provider = openai_translation_provider
    application.state.group_translation_service = GroupTranslationService(
        application.state.database,
        runtime_settings,
        group_crypto,
        openai_translation_provider,
        application.state.group_event_broker,
    )
    application.state.group_chat_translation_service = GroupChatTranslationService(
        application.state.database,
        runtime_settings,
        group_crypto,
        openai_translation_provider,
    )
    application.state.group_radio_floor = DistributedRadioFloor(runtime_settings)
    application.state.group_radio_service = GroupRadioService(
        application.state.database,
        runtime_settings,
        livekit_provider,
        application.state.group_event_broker,
    )
    application.state.room_manager = RoomManager(runtime_settings)
    application.state.timeblock_client = TimeblockClient(runtime_settings)
    application.state.bff_session_store = SessionStore(
        session_ttl_seconds=runtime_settings.guilua_session_ttl_seconds,
        pending_ttl_seconds=runtime_settings.guilua_pending_authorization_ttl_seconds,
        max_entries=runtime_settings.guilua_session_max_entries,
        max_pending_entries=runtime_settings.guilua_pending_authorization_max_entries,
        pending_rate_limit_count=runtime_settings.guilua_authorization_start_rate_limit_count,
        pending_rate_limit_window_seconds=(
            runtime_settings.guilua_authorization_start_rate_limit_window_seconds
        ),
    )
    application.mount('/static', StaticFiles(directory=BASE_DIR / 'app' / 'static'), name='static')

    @application.get('/service-worker.js', include_in_schema=False)
    async def service_worker() -> FileResponse:
        response = FileResponse(BASE_DIR / 'app' / 'static' / 'service-worker.js', media_type='application/javascript')
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    application.include_router(bff_router)
    application.include_router(group_handoff_v3_router)
    application.include_router(group_v3_router)
    application.include_router(group_v3_session_router)
    application.include_router(group_v3_translation_router)
    application.include_router(group_v3_radio_router)
    application.include_router(communication_router)

    @application.exception_handler(GroupServiceError)
    async def group_service_error(_request: Request, exc: GroupServiceError) -> JSONResponse:
        return JSONResponse(
            {"detail": exc.code},
            status_code=exc.status_code,
            headers={
                "Cache-Control": "no-store, private, max-age=0",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @application.get('/healthz/')
    async def healthz() -> dict[str, str]:
        return {'status': 'ok', 'service': 'guilua-communication-runtime'}

    @application.post('/internal/synthetics/group-v3/providers')
    async def group_v3_provider_synthetic(request: Request):
        """Provider-only readiness probe; never represents product acceptance."""
        supplied = str(request.headers.get('Authorization') or '')
        expected = str(runtime_settings.timeblock_api_key or '')
        if not expected or not supplied.startswith('Bearer ') or not secrets.compare_digest(supplied[7:], expected):
            return JSONResponse({'status': 'unauthorized'}, status_code=401)
        result: dict[str, object] = {
            'status': 'synthetic_validation',
            'product_acceptance': 'not_evaluated',
            'providers': {},
        }
        try:
            result['providers']['livekit'] = application.state.group_media_provider.synthetic_validate()
        except Exception as exc:
            result['providers']['livekit'] = {'status': 'unavailable', 'detail': str(exc)}
        try:
            result['providers']['openai_translation'] = application.state.openai_group_translation_provider.synthetic_validate()
        except Exception as exc:
            result['providers']['openai_translation'] = {'status': 'unavailable', 'detail': str(exc)}
        statuses = [item.get('status') for item in result['providers'].values() if isinstance(item, dict)]
        result['status'] = 'ready' if statuses and all(value == 'configured' for value in statuses) else 'not_ready'
        return JSONResponse(result, status_code=200 if result['status'] == 'ready' else 503)

    @application.get('/readyz/')
    async def readyz():
        schema_revision = None
        if runtime_settings.group_v3_enabled:
            try:
                application.state.database.ping()
            except Exception:
                return JSONResponse(
                    {
                        'status': 'not_ready',
                        'service': 'guilua-communication-runtime',
                        'dependency': 'group_v3_database',
                        'deployment_version': runtime_settings.deployment_version,
                    },
                    status_code=503,
                )
            try:
                revisions = application.state.database.migration_revisions()
            except Exception:
                revisions = ()
            if revisions != (GROUP_V3_SCHEMA_REVISION,):
                return JSONResponse(
                    {
                        'status': 'not_ready',
                        'service': 'guilua-communication-runtime',
                        'dependency': 'group_v3_schema',
                        'expected_revision': GROUP_V3_SCHEMA_REVISION,
                        'current_revisions': list(revisions),
                        'deployment_version': runtime_settings.deployment_version,
                    },
                    status_code=503,
                )
            schema_revision = GROUP_V3_SCHEMA_REVISION
        if runtime_settings.group_v3_enabled and runtime_settings.group_radio_v3_enabled:
            try:
                await application.state.group_radio_floor.ping()
            except GroupServiceError:
                return JSONResponse(
                    {
                        'status': 'not_ready',
                        'service': 'guilua-communication-runtime',
                        'dependency': 'group_radio_valkey',
                        'deployment_version': runtime_settings.deployment_version,
                    },
                    status_code=503,
                )
        if runtime_settings.development_session_fallback_enabled:
            payload = {
                'status': 'ready',
                'service': 'guilua-communication-runtime',
                'authority': 'development',
                'readiness_scope': 'dependencies_and_configuration',
                'product_acceptance': 'not_evaluated',
                'deployment_version': runtime_settings.deployment_version,
            }
            if runtime_settings.group_v3_enabled:
                payload.update(
                    {
                        'contract_version': '3',
                        'schema_revision': schema_revision,
                        'capabilities': {
                            'group_chat': True,
                            'group_media': runtime_settings.group_media_enabled,
                            'group_radio': runtime_settings.group_radio_v3_enabled,
                            'group_translation': runtime_settings.group_translation_enabled,
                        },
                    }
                )
            return payload
        try:
            manifest = await application.state.timeblock_client.contract_capabilities()
        except TimeblockIntegrationError:
            return JSONResponse(
                {
                    'status': 'not_ready',
                    'service': 'guilua-communication-runtime',
                    'dependency': 'timeblock_client_contract_v2',
                    'deployment_version': runtime_settings.deployment_version,
                },
                status_code=503,
            )
        if runtime_settings.group_v3_enabled:
            return {
                'status': 'ready',
                'service': 'guilua-communication-runtime',
                'authority': 'ai-communication',
                'readiness_scope': 'dependencies_and_configuration',
                'product_acceptance': 'not_evaluated',
                'contract_version': '3',
                'identity_authority': manifest['authority'],
                'identity_contract_version': manifest['contract_version'],
                'schema_revision': schema_revision,
                'capabilities': {
                    'group_chat': True,
                    'group_media': runtime_settings.group_media_enabled,
                    'group_radio': runtime_settings.group_radio_v3_enabled,
                    'group_translation': runtime_settings.group_translation_enabled,
                },
                'deployment_version': runtime_settings.deployment_version,
            }
        return {
            'status': 'ready',
            'service': 'guilua-communication-runtime',
            'authority': manifest['authority'],
            'readiness_scope': 'dependencies_and_configuration',
            'product_acceptance': 'not_evaluated',
            'contract_version': manifest['contract_version'],
            'deployment_version': runtime_settings.deployment_version,
        }

    return application


app = create_app()
