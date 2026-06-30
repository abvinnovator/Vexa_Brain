from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from config import settings
from services import mongodb_service
from routers import chat, action
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Init agents packages ──────────────────────────────────
import agents  # noqa: ensures submodule init

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await mongodb_service.connect(settings.mongodb_uri, settings.mongodb_db_name)
    logger.info("Vexa Brain started ✓")
    yield
    # Shutdown
    await mongodb_service.disconnect()
    logger.info("Vexa Brain stopped")


app = FastAPI(
    title="Vexa Brain",
    description="AI engine for personal phone automation. The phone acts — Vexa thinks.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS — allow Android app on local network
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(chat.router, prefix="/api")
app.include_router(action.router, prefix="/api")


@app.get("/")
async def root():
    return {"name": "Vexa Brain", "status": "running", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=settings.debug)
