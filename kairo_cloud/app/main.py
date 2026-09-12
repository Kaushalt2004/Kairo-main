import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router, ws_router
from app.core.config import settings
from app.core.database import engine, Base
from app.core.redis import redis_manager
# Import all models to ensure metadata registration
import app.models

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger("kairo_cloud")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing Kairo Cloud Platform...")
    # Initialize DB tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schemas verified.")

    # Auto-seed default vehicles and users
    try:
        from db.seed_data import seed
        await seed()
    except Exception as e:
        logger.debug("Auto-seed info: %s", e)

    # Initialize Redis connection pool
    await redis_manager.connect()
    yield

    # Shutdown
    logger.info("Shutting down Kairo Cloud Platform...")
    await redis_manager.close()
    await engine.dispose()
    logger.info("Kairo Cloud Platform shutdown complete.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Enterprise Cloud Connectivity & Fleet Management Platform for Autonomous Mobility (CARLA, Apollo 9, ROS 2, OEM).",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root Health & Readiness Probes
@app.get("/healthz", tags=["System"])
async def health_check():
    """Liveness probe."""
    return {"status": "healthy", "service": "kairo-cloud-backend", "version": "1.0.0"}


@app.get("/readyz", tags=["System"])
async def readiness_check():
    """Readiness probe checking Redis and Database availability."""
    redis_status = "connected" if redis_manager.is_connected else "in-memory-fallback"
    return {
        "status": "ready",
        "redis": redis_status,
        "database": "connected"
    }


# Attach Routers
app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(ws_router)

# Mount Web Dashboard
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(static_dir), html=True), name="static")

@app.get("/", include_in_schema=False)
async def root():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"status": "healthy", "service": "kairo-cloud-backend"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
