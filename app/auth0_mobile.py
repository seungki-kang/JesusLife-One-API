"""Explicit opt-in local Android entry point; also preserves PC routes.

No DDL, external requests or DB connection occurs at import/startup.
"""
from dotenv import dotenv_values
from app.auth0_pc import PcRuntime, create_app
from app.core.mobile_store import MobileCoreStore
from scripts.auth0_pc_settings import PATH, validate


def configured_app():
    try:
        config = validate(dotenv_values(PATH, interpolate=False))
        return create_app(PcRuntime(config, store=MobileCoreStore(config.encryption_key, config.hmac_key)))
    except Exception:
        return create_app()


app = configured_app()
