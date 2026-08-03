from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from config import settings
from services import mongodb_service, knowledge_service, tracing_service, neo4j_service
from routers import chat, action, knowledge, agent, email
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Init agents packages ──────────────────────────────────
import agents  # noqa: ensures submodule init

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await mongodb_service.connect(settings.mongodb_uri, settings.mongodb_db_name)

    # Initialize OKF knowledge service with Neo4j Graph DB
    await knowledge_service.init_async()
    stats = knowledge_service.get_stats()
    logger.info(f"OKF Knowledge Base: {stats['total_nodes']} nodes, {stats['total_tags']} tags, domains={stats['domains']}, neo4j={stats['neo4j_connected']}")

    # Initialize LangSmith tracing
    tracing_service.init()

    logger.info("Vexa Brain started ✓")
    yield
    # Shutdown
    await mongodb_service.disconnect()
    await neo4j_service.disconnect()
    logger.info("Vexa Brain stopped")


app = FastAPI(
    title="Vexa Brain",
    description="AI engine for personal phone automation with self-learning OKF knowledge base. The phone acts — Vexa thinks.",
    version="3.0.0",
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
app.include_router(knowledge.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(email.router, prefix="/api")


@app.get("/")
async def root():
    return {
        "name": "Vexa Brain",
        "status": "running",
        "version": "3.0.0",
        "architecture": "OKF (Open Knowledge Format)",
        "features": [
            "Self-learning knowledge base",
            "Personalized response matching",
            "Phone automation (action steps)",
            "Saved agents (replay without AI)",
            "LLM observability (LangSmith)",
            "Email send (Gmail SMTP)",
            "Email inbox (Gmail IMAP)"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=settings.debug)
