"""
FastAPI Web Server Entrypoint Application for Taproot Phase 1.
Configures CORS, exception handlers, REST routers, and static asset streaming.
Matches Section 26 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from backend.routes import documents

app = FastAPI(
    title="TAPROOT Phase 1 Ingestion API",
    description="CPU-First Educational PDF Ingestion & Structuring Pipeline Server",
    version="2026.09.0",
)

# Configure CORS Middleware for Frontend Verification UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount REST API Routers
app.include_router(documents.router, prefix="/documents", tags=["documents"])


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
        "service": "TAPROOT Phase 1 Ingestion Pipeline",
        "version": "2026.09.0",
    }
