from fastapi import FastAPI

from app.modules.neorang_narang.router import router as neorang_narang_router

app = FastAPI(
    title="JesusLife One API",
    description="JesusLife One 서비스들을 연결하는 공통 API",
    version="0.1.0",
)

app.include_router(neorang_narang_router)


@app.get("/")
async def root():
    return {"message": "JesusLife One API가 실행 중입니다."}


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "jesuslife-one-api",
        "version": "0.1.0",
    }
