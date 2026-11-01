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
from backend.routes import curriculum, documents, api
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

import sys
if sys.platform == "win32":
    # Workaround for CPython issue #84882 / uvicorn issue #1126 on Windows:
    # When a client resets a connection before accept() completes, Windows raises
    # WinError 64 / 121 / 10054. The standard asyncio proactor event loop unhandled exception
    # handler closes the server listening socket, killing the server.
    # We patch BaseProactorEventLoop._start_serving to ignore transient client aborts and keep listening.
    try:
        import asyncio.proactor_events as _pe
        _orig_start_serving = _pe.BaseProactorEventLoop._start_serving

        def _patched_start_serving(self, protocol_factory, sock, sslcontext=None, server=None, backlog=100, ssl_handshake_timeout=None, ssl_shutdown_timeout=None):
            def loop(f=None):
                try:
                    if f is not None:
                        try:
                            conn, addr = f.result()
                        except OSError as exc:
                            if getattr(exc, "winerror", None) in (64, 121, 10054):
                                if not self.is_closed():
                                    next_f = self._proactor.accept(sock)
                                    self._accept_futures[sock.fileno()] = next_f
                                    next_f.add_done_callback(loop)
                                return
                            raise
                        protocol = protocol_factory()
                        if sslcontext is not None:
                            self._make_ssl_transport(
                                conn, protocol, sslcontext, server_side=True,
                                extra={"peername": addr}, server=server,
                                ssl_handshake_timeout=ssl_handshake_timeout,
                                ssl_shutdown_timeout=ssl_shutdown_timeout)
                        else:
                            self._make_socket_transport(
                                conn, protocol,
                                extra={"peername": addr}, server=server)
                    if self.is_closed():
                        return
                    f = self._proactor.accept(sock)
                except OSError as exc:
                    if getattr(exc, "winerror", None) in (64, 121, 10054):
                        if not self.is_closed():
                            next_f = self._proactor.accept(sock)
                            self._accept_futures[sock.fileno()] = next_f
                            next_f.add_done_callback(loop)
                        return
                    if sock.fileno() != -1:
                        self.call_exception_handler({
                            "message": "Accept failed on a socket",
                            "exception": exc,
                            "socket": _pe.trsock.TransportSocket(sock),
                        })
                        sock.close()
                    elif self._debug:
                        _pe.logger.debug("Accept failed on socket %r", sock, exc_info=True)
                except _pe.exceptions.CancelledError:
                    sock.close()
                else:
                    self._accept_futures[sock.fileno()] = f
                    f.add_done_callback(loop)

            self.call_soon(loop)

        _pe.BaseProactorEventLoop._start_serving = _patched_start_serving
    except Exception:
        pass



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
        storage_dirs = ["storage/subjects", "storage/learners", "storage/sessions", "storage/resources", "storage/classes"]
        for d in storage_dirs:
            Path(d).mkdir(parents=True, exist_ok=True)
        results["storage"] = {"status": "OK"}
    except Exception as exc:
        results["storage"] = {"status": "FAILED", "reason": str(exc)}

    # --- Video & Resource Recommender (§9) ---
    try:
        from backend.services.resource_service import ResourceService
        res_svc = ResourceService()
        all_res = res_svc.list_all_resources()
        results["resources"] = {"status": "OK", "count": len(all_res)}
    except Exception as exc:
        results["resources"] = {"status": "FAILED", "reason": str(exc)}

    # --- Teacher Optimizer (§10) ---
    try:
        from backend.services.teacher_service import TeacherService
        TeacherService()
        results["teacher_optimizer"] = {"status": "OK"}
    except Exception as exc:
        results["teacher_optimizer"] = {"status": "FAILED", "reason": str(exc)}

    # --- Canonical Curriculum (§Person 2) ---
    try:
        from backend.services.curriculum_service import CurriculumService
        curr_svc = CurriculumService()
        if curr_svc.has_curriculum:
            graph = curr_svc.get_graph()
            results["curriculum"] = {
                "status": "OK",
                "curriculum_id": curr_svc.curriculum_id,
                "concept_count": len(graph.concepts),
                "fingerprint": graph.content_fingerprint(),
            }
        else:
            results["curriculum"] = {"status": "UNSEEDED", "reason": "No curriculum seeded yet"}
    except Exception as exc:
        results["curriculum"] = {"status": "FAILED", "reason": str(exc)}

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
# Canonical curriculum & knowledge graph (Person 2): /api/curriculum/...
app.include_router(curriculum.router, prefix="/api", tags=["curriculum"])


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
