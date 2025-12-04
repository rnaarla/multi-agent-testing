"""
Multi-Agent Behavioral Testing Platform API

Enterprise-grade framework for evaluating multi-agent systems through
behavioral test graphs with support for:
- Deterministic execution with seed control
- Contract validation between agents
- Multi-provider LLM support (OpenAI, Anthropic, Azure, etc.)
- PII detection and governance controls
- Background execution with webhooks
- Comprehensive metrics and drift detection
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import os
import structlog

from app.routers import graphs, runs, metrics, auth, release, analytics, collab, user_testing
from app.database import init_db
from app.utils.request_context import RequestContextMiddleware
from app.config import get_settings
from app.observability import setup_observability
from app.observability.logging import RequestLoggingMiddleware
from app.reliability import load_default_slos

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Multi-Agent Testing Platform...")
    init_db()
    logger.info("Database initialized")
    yield
    # Shutdown
    logger.info("Shutting down...")


app = FastAPI(
    title="Multi-Agent Behavioral Testing Platform",
    description="""
    Enterprise-grade framework for evaluating multi-agent systems through behavioral test graphs.
    
    ## Features
    - **Graph Management**: Upload and version YAML-defined behavioral test graphs
    - **Test Execution**: Run tests with deterministic seed control and replay capability
    - **Contract Validation**: Enforce contracts between agent nodes
    - **Multi-Provider**: Support for OpenAI, Anthropic, Azure, Ollama, and more
    - **Governance**: PII detection, policy enforcement, safety scoring
    - **Metrics**: Latency tracking, cost accounting, drift detection
    - **Async Execution**: Background workers with webhook notifications
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Load settings once
settings = get_settings()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestContextMiddleware)
app.add_middleware(RequestLoggingMiddleware)

# Observability (logging/tracing/metrics)
setup_observability(app)

# Expose settings for other components (e.g., CLI tooling, scripts)
app.state.settings = settings
app.extra["hot_reload"] = settings.enable_hot_reload
app.state.slos = load_default_slos()

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(graphs.router, prefix="/graphs", tags=["Test Graphs"])
app.include_router(runs.router, prefix="/runs", tags=["Test Runs"])
app.include_router(metrics.router, prefix="/metrics", tags=["Metrics & Analytics"])
app.include_router(release.router, prefix="/release", tags=["Release Guard"])
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
app.include_router(collab.router, prefix="/collab", tags=["Collaboration"])
app.include_router(user_testing.router, prefix="/user-testing", tags=["User Testing"])


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__}
    )


@app.get("/", tags=["Health"])
def root():
    """Health check endpoint."""
    return {
        "status": "running",
        "service": "Multi-Agent Behavioral Testing Platform",
        "version": "1.0.0"
    }


@app.get("/health", tags=["Health"])
def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "components": {
            "api": "up",
            "database": "up"  # TODO: Add actual DB check
        }
    }


@app.get("/providers", tags=["Configuration"])
def list_available_providers():
    """List available LLM providers."""
    from app.providers import ProviderRegistry
    registry = ProviderRegistry()
    return {
        "available": registry.list_available_providers(),
        "configured": registry.list_providers()
    }
