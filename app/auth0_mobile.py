"""Explicit opt-in local Android entry point; also preserves PC routes.

No DDL, external requests or DB connection occurs at import/startup.
"""
from dotenv import dotenv_values
from app.auth0_pc import PcRuntime, create_app
from app.core.mobile_store import MobileCoreStore
from scripts.auth0_pc_settings import PATH, validate


def create_development_app(parent, *, life_diary_config=None, enabled=False, provider=None,
                           callback_uri=None):
    """Explicit server-owned development opt-in; never reads extra settings."""
    if enabled:
        if parent is None or life_diary_config is None:
            raise ValueError('Life Diary development configuration required')
        policy = life_diary_config.policy
        if (len(policy.client_ids) != 1
                or policy.client_ids & parent.config.policy.client_ids
                or policy.issuer != parent.config.policy.issuer
                or policy.audience != parent.config.policy.audience
                or not life_diary_config.client_secret
                or life_diary_config.encryption_key != parent.config.encryption_key
                or life_diary_config.hmac_key != parent.config.hmac_key):
            raise ValueError('Invalid Life Diary development configuration')
        from app.core.life_diary_login import Registration, CALLBACK, DEVELOPMENT_CALLBACK
        if callback_uri not in (None, CALLBACK, DEVELOPMENT_CALLBACK):
            raise ValueError('Invalid Life Diary callback')
        child = PcRuntime(life_diary_config, store=parent.store,
                          provider=provider, clock=parent.clock)
        parent.life_diary_registration = Registration(next(iter(policy.client_ids)), enabled=True,
                                                     callback_uri=callback_uri or CALLBACK)
        parent.life_diary_runtime = child
    elif parent is not None:
        # Also close a previously wired parent when explicit opt-in is removed.
        parent.life_diary_registration = None
        parent.life_diary_runtime = None
    hosts = None
    if enabled and callback_uri == DEVELOPMENT_CALLBACK:
        hosts = ['127.0.0.1', 'unwary-founder-peculiar.ngrok-free.dev']
    app = create_app(parent, trusted_hosts=hosts)
    if hosts:
        from fastapi.responses import JSONResponse

        @app.middleware('http')
        async def development_host_boundary(request, call_next):
            if (request.url.hostname != '127.0.0.1'
                    and (request.url.hostname != 'unwary-founder-peculiar.ngrok-free.dev'
                         or request.url.path != '/api/v1/auth/callback/life-diary/android'
                         or request.method != 'GET')):
                return JSONResponse({'detail': 'Access denied'}, status_code=403)
            return await call_next(request)
    return app


def configured_app():
    try:
        config = validate(dotenv_values(PATH, interpolate=False))
        return create_development_app(PcRuntime(config, store=MobileCoreStore(config.encryption_key, config.hmac_key)))
    except Exception:
        return create_development_app(None)


app = configured_app()
