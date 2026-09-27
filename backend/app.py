"""
FastAPI Web Server Entrypoint Application for Taproot Platform.
Configures CORS, exception handlers, REST routers, and application services.
"""

import os
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from backend.routes import documents, phase4, api

app = FastAPI(
    title="TAPROOT Adaptive Learning Platform API",
    description="Unified Adaptive Learning Platform API (Phases 1-6)",
    version="2026.09.0",
)

# Environment-driven CORS configuration for frontend integration
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if allowed_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount REST API Routers
app.include_router(api.router, prefix="/api", tags=["application_facades"])
app.include_router(documents.router, prefix="/documents", tags=["documents"])
app.include_router(phase4.router, prefix="/phase4", tags=["phase4"])


@app.exception_handler(ValueError)
async def value_error_exception_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "VALIDATION_ERROR", "message": str(exc)},
    )


@app.get("/health", tags=["health"])
async def health_check():
    return {
        "status": "healthy",
        "service": "TAPROOT Adaptive Learning Platform API",
        "version": "2026.09.0",
    }
