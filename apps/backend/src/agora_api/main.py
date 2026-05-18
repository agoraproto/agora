"""FastAPI application entrypoint."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import get_settings
from .logging import configure_logging, get_logger
from .rate_limit import limiter
from .routes import agents, health, jobs, payments, reviews, search, stats, well_known, x402
from .webhooks.delivery import worker_loop

settings = get_settings()
configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("agora_api.startup", env=settings.app_env, chain_id=settings.chain_id)
    stop_event = asyncio.Event()
    worker_task: asyncio.Task | None = None
    if settings.webhook_worker_enabled:
        worker_task = asyncio.create_task(worker_loop(stop_event), name="webhook-worker")
    try:
        yield
    finally:
        if worker_task is not None:
            stop_event.set()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()
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

# ─── Rate-Limiting (slowapi) ────────────────────────────
# Limits are per-route; see .rate_limit and per-route decorators.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ─── CORS ────────────────────────────────────────────────
# Public endpoints (/.well-known, /v1/search, /v1/stats, /v1/agents) are
# read-only and benefit from being callable from any origin (third-party
# dashboards, AI crawlers, marketplaces). State-changing endpoints rely on
# signed payloads + DID auth in future iterations, not on CORS.
ALLOWED_ORIGINS: list[str] | str = ["*"]
if settings.app_env in ("staging", "production"):
    ALLOWED_ORIGINS = [
        "https://agoraproto.org",
        "https://www.agoraproto.org",
        "https://api.agoraproto.org",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(agents.router, prefix="/v1/agents", tags=["agents"])
app.include_router(search.router, prefix="/v1", tags=["discovery"])
app.include_router(jobs.router, prefix="/v1/jobs", tags=["jobs"])
app.include_router(x402.router, prefix="/v1/x402", tags=["x402"])
app.include_router(payments.router, prefix="/v1/payments", tags=["payments"])
app.include_router(reviews.router, prefix="/v1", tags=["reputation"])
app.include_router(stats.router, prefix="/v1", tags=["stats"])
app.include_router(well_known.router, tags=["well-known"])


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": "agora-api",
        "version": "0.1.0",
        "docs": "/docs",
    }
