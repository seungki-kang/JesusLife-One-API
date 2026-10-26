from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/neorang-narang", tags=["neorang-narang"])


@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "neorang-narang",
        "version": "0.1.0",
    }
