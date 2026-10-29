"""
Nexora Backend Application
FastAPI application entry point
"""
import asyncio
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from nexora.backend.app.api.routes import router as api_router
from nexora.backend.app.api.package_routes import router as package_router
from nexora.backend.app.core.database import close_db, init_db
from nexora.backend.config.settings import get_settings

settings = get_settings()


# ---------------------------------------------------------------------------
# Security: Log Injection / CRLF Sanitization Filter (CWE-117)
# ---------------------------------------------------------------------------
class SafeLogFilter(logging.Filter):
    """Sanitizes log records to prevent log injection and CRLF forging."""
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = record.msg.replace("\r", "\\r").replace("\n", "\\n")
        return True

logging.getLogger().addFilter(SafeLogFilter())


# ---------------------------------------------------------------------------
# Security: Defense-in-Depth HTTP Headers & CSP Middleware
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces standard security headers on all HTTP responses."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        if "Content-Security-Policy" not in response.headers:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self' http://127.0.0.1:* http://localhost:*; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
                "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net data:; "
                "img-src 'self' data: https:; "
                "connect-src 'self' http://127.0.0.1:* http://localhost:*; "
                "frame-ancestors 'self';"
            )
        return response


# ---------------------------------------------------------------------------
# Security: Request Payload Body Size Limiter (DoS Prevention)
# ---------------------------------------------------------------------------
class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects oversized payloads before parsing to prevent memory exhaustion."""
    def __init__(self, app, max_bytes: int = 10 * 1024 * 1024):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Request payload too large. Maximum allowed size is {self.max_bytes // (1024*1024)} MB."},
                    )
            except ValueError:
                pass
        return await call_next(request)


# ---------------------------------------------------------------------------
# Security: In-Memory Sliding-Window Rate Limiter (Token Drain & DoS Prevention)
# ---------------------------------------------------------------------------
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforces per-client IP sliding-window rate limits."""
    def __init__(self, app, rpm: int = 120, run_rpm: int = 30):
        super().__init__(app)
        self.rpm = rpm
        self.run_rpm = run_rpm
        self.requests = defaultdict(list)
        self.run_requests = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Health check and documentation paths are unrestricted
        if path in ("/api/v1/health", "/", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        # Allow test suites to bypass if explicitly header-flagged
        if request.headers.get("X-Test-Client") == "true":
            return await call_next(request)

        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        window_start = now - 60.0

        # Prune expired timestamps
        self.requests[client_ip] = [t for t in self.requests[client_ip] if t > window_start]
        self.run_requests[client_ip] = [t for t in self.run_requests[client_ip] if t > window_start]

        # Specific strict limit on run creation to stop token depletion loops
        if request.method == "POST" and path == "/api/v1/runs":
            if len(self.run_requests[client_ip]) >= self.run_rpm:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Run creation rate limit exceeded. Please wait a moment before creating another run."},
                    headers={"Retry-After": "60"},
                )
            self.run_requests[client_ip].append(now)

        # Overall API rate limit
        if len(self.requests[client_ip]) >= self.rpm:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": "60"},
            )
        self.requests[client_ip].append(now)

        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager"""
    import logging
    _log = logging.getLogger(__name__)

    # Startup security sanity-checks (non-fatal in dev; fatal in production
    # is enforced at the Settings level).
    if settings.DEBUG and not settings.SECRET_KEY:
        _log.warning(
            "SECURITY: DEBUG=true with an empty SECRET_KEY. "
            "Set SECRET_KEY before deploying to a non-local environment."
        )
    if settings.DEBUG:
        _log.warning(
            "SECURITY: DEBUG=true — Swagger UI (/docs, /redoc) is publicly accessible."
        )

    await init_db()
    
    # Start background worker
    # worker_task = asyncio.create_task(run_worker())
    
    yield
    
    # Shutdown
    # worker_task.cancel()
    # try:
    #     await worker_task
    # except asyncio.CancelledError:
    #     pass
    
    await close_db()


app = FastAPI(
    title="Nexora API",
    description="Secure, token-efficient adaptive coding agent",
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# Security Middlewares
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=10 * 1024 * 1024)
app.add_middleware(RateLimitMiddleware, rpm=120, run_rpm=30)

# CORS — restrict to the methods and headers actually used by the API.
# allow_methods=["*"] and allow_headers=["*"] would accept arbitrary HTTP
# methods/headers from configured origins; tighten both to the explicit set.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)

# API routes
app.include_router(api_router, prefix="/api/v1")
# Standalone packages/* layer (contracts, model_router, nebius_adapter)
app.include_router(package_router, prefix="/api/v1")

# Mount frontend static files (in production)
import os
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Nexora",
        "version": "3.0.0",
        "description": "Secure, token-efficient adaptive coding agent",
        "docs": "/docs",
    }


@app.get("/api/v1/health")
async def health():
    """Health check"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "nexora.backend.app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
