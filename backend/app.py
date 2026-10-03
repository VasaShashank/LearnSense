"""
FastAPI Web Server Entrypoint Application for Taproot Platform.
Configures CORS, exception handlers, REST routers, and application services.
"""

import logging
import os
from pathlib import Path
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from backend.routes import documents, api
from phase3.errors import LearnSenseError

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# W1: Startup Preflight — probes each subsystem and caches the results.
# The app still starts so that /api/system/feature-status can be queried,
# but failed subsystems are logged and reported honestly.
# ---------------------------------------------------------------------------

_preflight_results: dict = {}


def _run_startup_preflight() -> dict:
    """Probe LLM, VLM, OCR, and storage. Returns a dict keyed by subsystem."""
    results = {}

    # --- LLM ---
    try:
        from phase3.adapters.llm_adapter import get_llm_adapter
        adapter = get_llm_adapter()
        health = adapter.health()
        is_mock = getattr(adapter, "is_mock", False)
        if is_mock:
            results["llm"] = {"status": "DISABLED_BY_CONFIG", "reason": "Mock adapter active (test-only)"}
        elif health.get("has_credentials") and health.get("provider"):
            results["llm"] = {"status": "OK", "provider": health.get("provider")}
        else:
            results["llm"] = {"status": "FAILED", "reason": "No credentials or provider configured"}
    except Exception as exc:
        results["llm"] = {"status": "FAILED", "reason": str(exc)}

    # --- VLM ---
    try:
        vlm_provider = os.getenv("VLM_PROVIDER", "")
        vlm_model = os.getenv("VLM_MODEL", "")
        vlm_mode = os.getenv("VLM_MODE", "")
        if vlm_mode == "disabled":
            results["vlm"] = {"status": "DISABLED_BY_CONFIG"}
        elif vlm_provider and vlm_model:
            results["vlm"] = {"status": "OK", "provider": vlm_provider, "model": vlm_model}
        else:
            results["vlm"] = {"status": "FAILED", "reason": "VLM_PROVIDER and VLM_MODEL must be set"}
    except Exception as exc:
        results["vlm"] = {"status": "FAILED", "reason": str(exc)}

    # --- OCR ---
    try:
        from adapters.tesseract_adapter import TesseractOCRAdapter
        ocr = TesseractOCRAdapter()
        ocr._sync_tesseract_cmd()
        import pytesseract
        ver = str(pytesseract.get_tesseract_version())
        results["ocr"] = {"status": "OK", "version": ver, "languages": ocr.languages}
    except Exception as exc:
        results["ocr"] = {"status": "FAILED", "reason": str(exc)}

    # --- Storage ---
    try:
        storage_dirs = ["storage/subjects", "storage/learners", "storage/sessions"]
        for d in storage_dirs:
            Path(d).mkdir(parents=True, exist_ok=True)
        results["storage"] = {"status": "OK"}
    except Exception as exc:
        results["storage"] = {"status": "FAILED", "reason": str(exc)}

    return results


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


@app.on_event("startup")
async def on_startup():
    global _preflight_results
    logger.info("Running startup preflight checks...")
    _preflight_results = _run_startup_preflight()
    for subsystem, result in _preflight_results.items():
        st = result.get("status", "UNKNOWN")
        if st == "OK":
            logger.info("Preflight [%s]: %s", subsystem, st)
        elif st == "DISABLED_BY_CONFIG":
            logger.info("Preflight [%s]: %s — %s", subsystem, st, result.get("reason", ""))
        else:
            logger.warning("Preflight [%s]: %s — %s", subsystem, st, result.get("reason", ""))


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
        "feature_status": "/api/system/feature-status",
    }


@app.get("/health", tags=["health"])
async def health_check():
    # Report subsystem readiness from the preflight probe.
    all_ok = all(r.get("status") == "OK" for r in _preflight_results.values()) if _preflight_results else False
    return {
        "status": "healthy" if all_ok else "degraded",
        "service": "TAPROOT Adaptive Learning Platform API",
        "version": "2026.09.0",
        "subsystems": {k: v.get("status", "UNKNOWN") for k, v in _preflight_results.items()},
    }


@app.get("/api/system/feature-status", tags=["system"])
async def feature_status():
    """
    W1: Returns real probe evidence for each subsystem.
    Status values: OK | FAILED | DISABLED_BY_CONFIG | NOT_IMPLEMENTED
    """
    return {
        "subsystems": _preflight_results or {"_": {"status": "NOT_IMPLEMENTED", "reason": "Preflight not yet run"}},
    }
