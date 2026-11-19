from fastapi import FastAPI

from app.modules.neorang_narang.router import router as neorang_narang_router


def create_app(
    *, life_diary_backup_owner=None, life_diary_backup_connect=None,
    life_diary_runtime=None, life_diary_public_origin=None,
):
    """Build One API with optional, explicitly supplied Life Diary dependencies."""
    cloud_login = life_diary_runtime is not None or life_diary_public_origin is not None
    if cloud_login and (
        life_diary_runtime is None or life_diary_public_origin is None
        or not callable(life_diary_backup_connect) or life_diary_backup_owner is not None
    ):
        raise ValueError("Cloud Life Diary requires its runtime, HTTPS origin and backup connector")

    backup_dependencies = (life_diary_backup_owner, life_diary_backup_connect)
    backup_enabled = any(dependency is not None for dependency in backup_dependencies)
    if backup_enabled and not cloud_login and not all(callable(dependency) for dependency in backup_dependencies):
        raise ValueError("Life Diary backup requires both an owner resolver and a database connector")

    api = FastAPI(
        title="JesusLife One API",
        description="JesusLife One 서비스들을 연결하는 공통 API",
        version="0.1.0",
    )

    api.include_router(neorang_narang_router)

    if cloud_login:
        from app.core.life_diary_login import cloud_callback, install_life_diary
        from app.modules.life_diary.completed_backup_routes import create_completed_backup_router

        callback = cloud_callback(life_diary_public_origin)
        registration = getattr(life_diary_runtime, "life_diary_registration", None)
        if not registration or not registration.enabled or registration.callback_uri != callback:
            raise ValueError("Life Diary runtime must register the configured HTTPS callback")
        install_life_diary(
            api, lambda: life_diary_runtime, public_origin=life_diary_public_origin,
            backup_router_factory=lambda owner: create_completed_backup_router(
                owner, life_diary_backup_connect
            ),
        )
    elif backup_enabled:
        from app.modules.life_diary.completed_backup_routes import create_completed_backup_router

        api.include_router(
            create_completed_backup_router(life_diary_backup_owner, life_diary_backup_connect)
        )

    @api.get("/")
    async def root():
        return {"message": "JesusLife One API가 실행 중입니다."}

    @api.get("/health")
    async def health_check():
        return {
            "status": "ok",
            "service": "jesuslife-one-api",
            "version": "0.1.0",
        }

    return api


app = create_app()
