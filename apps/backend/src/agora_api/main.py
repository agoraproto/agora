"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .logging import configure_logging, get_logger
from .routes import agents, health, jobs, payments, reviews, search

settings = get_settings()
configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("agora_api.startup", env=settings.app_env, chain_id=settings.chain_id)
    yield
    log.info("agora_api.shutdown")


app = FastAPI(
    title="Agora API",
    description="Open marketplace and communication protocol for AI agents.",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/v1/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(health.router, tags=["health"])
app.include_router(agents.router, prefix="/v1/agents", tags=["agents"])
app.include_router(search.router, prefix="/v1", tags=["discovery"])
app.include_router(jobs.router, prefix="/v1/jobs", tags=["jobs"])
app.include_router(payments.router, prefix="/v1/payments", tags=["payments"])
app.include_router(reviews.router, prefix="/v1", tags=["reputation"])


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": "agora-api",
        "version": "0.1.0",
        "docs": "/docs",
    }
