"""
FastAPI Web Server Entrypoint Application for Taproot Platform.
Configures CORS, exception handlers, REST routers, and application services.
"""

import os
from pathlib import Path
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from backend.routes import documents, api
from phase3.errors import LearnSenseError

# Load environment configuration if .env exists
for p in [Path(".env"), Path(__file__).resolve().parent.parent / ".env"]:
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v

app = FastAPI(
    title="TAPROOT Adaptive Learning Platform API",
    description="Unified Adaptive Learning Platform API (Phases 1-7)",
    version="2026.09.0",
)

# Environment-driven CORS configuration for frontend integration
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]
if "*" in allowed_origins or not allowed_origins:
    allowed_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount REST API Routers
app.include_router(api.router, prefix="/api", tags=["application_facades"])
app.include_router(documents.router, prefix="/documents", tags=["documents"])


@app.exception_handler(ValueError)
async def value_error_exception_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "VALIDATION_ERROR", "message": str(exc)},
    )


@app.exception_handler(LearnSenseError)
async def learnsense_error_handler(request: Request, exc: LearnSenseError):
    """
    Render every typed runtime error with its machine-readable code and retry state.

    Without this, a route-level ``except Exception`` turned "the LLM provider is rate
    limited" into an opaque 400 with no indication that retrying would succeed, and the
    frontend had no way to distinguish a transient failure from a bad upload.
    """
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error": exc.code,
            "code": exc.code,
            "message": str(exc),
            "recoverable": exc.recoverable,
            "details": exc.details,
        },
        headers={"Retry-After": "5"} if exc.recoverable else None,
    )


@app.get("/", tags=["root"])
async def root():
    return {
        "message": "LearnSense / TAPROOT API is running.",
        "frontend_url": "http://localhost:5173",
        "api_documentation": "/docs",
        "health_check": "/health",
    }


@app.get("/health", tags=["health"])
async def health_check():
    return {
        "status": "healthy",
        "service": "TAPROOT Adaptive Learning Platform API",
        "version": "2026.09.0",
    }
