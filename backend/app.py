"""
FastAPI Web Server Entrypoint Application for Taproot Platform.
Configures CORS, exception handlers, REST routers, and application services.
"""

import logging
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from backend.routes import curriculum, documents, api
from phase3.errors import LearnSenseError

logger = logging.getLogger(__name__)

# The institutional service selects its persistence backend during route
# import. Load only those settings before importing routes; loading unrelated
# configuration here can initialize other integrations with changed behavior.
for p in [Path(".env"), Path(__file__).resolve().parent.parent / ".env"]:
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k in {"DATABASE_URL", "LEARNSENSE_REQUIRE_PG", "LEARNSENSE_ENV"} and k not in os.environ:
                        os.environ[k] = v

# Import routes only after environment loading: the institutional service
# selects PostgreSQL vs JSON persistence when it is constructed at import time.
from backend.routes import documents, api

# Preserve the app's existing configuration loading order for other settings.
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
    except Exception as exc:
        logging.getLogger(__name__).debug("Proactor loop patch skipped: %s", exc)



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

# CORS: explicit origins only. A wildcard is never combined with credentials, and
# strict environments (staging/production) fail startup without explicit origins.
from backend.config import cors_settings, enforce_runtime_config, is_strict  # noqa: E402
from backend.api_errors import install_error_handlers  # noqa: E402

allowed_origins, allow_credentials = cors_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_error_handlers(app)

# Mount REST API Routers
app.include_router(api.router, prefix="/api", tags=["application_facades"])
app.include_router(documents.router, prefix="/documents", tags=["documents"])
# Canonical curriculum & knowledge graph (Person 2): /api/curriculum/...
app.include_router(curriculum.router, prefix="/api", tags=["curriculum"])


async def _optional_pg_schema_status() -> dict:
    """Optional PostgreSQL mode: report schema state loudly, never block startup."""
    import asyncio

    from backend.db.pg_connection import get_pg_pool
    from backend.db.schema_check import describe_report, has_problems, inspect_migrations
    from backend.services.institution_service import _await_background

    async def _check():
        return await inspect_migrations(await get_pg_pool())

    try:
        report = await asyncio.wait_for(_await_background(_check()), timeout=15)
    except Exception as exc:
        reason = f"could not verify migrations ({type(exc).__name__})"
        logger.warning("PostgreSQL is configured but %s; schema readiness is UNVERIFIED.", reason)
        return {"status": "FAILED", "reason": reason}
    if has_problems(report):
        banner = "=" * 72
        logger.warning(
            "\n%s\nPOSTGRESQL SCHEMA NOT READY - institutional features may fail.\n%s\n%s",
            banner, describe_report(report), banner,
        )
        summary = "; ".join(
            f"{label}: {', '.join(report[key])}"
            for key, label in (("missing", "migrations not recorded"),
                               ("modified", "checksum mismatch"),
                               ("unverified", "checksum not recorded"))
            if report[key]
        )
        return {"status": "FAILED", "reason": summary}
    return {"status": "OK"}


@app.on_event("startup")
async def on_startup():
    global _preflight_results
    # Fails startup in staging/production when required settings are missing or
    # unsafe. Names the settings only; never their values.
    enforce_runtime_config()
    # Refuse a transaction-pooler DATABASE_URL in every mode (credential-free message);
    # the asyncpg pool cannot work reliably through it.
    from backend.db.pg_connection import UnsupportedConnectionError, api_connection_problem
    from backend.db.pg_connection import is_pg_configured as _pg_configured

    if _pg_configured():
        problem = api_connection_problem(os.environ["DATABASE_URL"].strip())
        if problem:
            raise UnsupportedConnectionError(problem)
    pg_schema = None
    if os.getenv("LEARNSENSE_REQUIRE_PG", "0").strip() == "1":
        from backend.db.pg_connection import get_pg_pool, is_pg_configured

        if not is_pg_configured():
            raise RuntimeError(
                "LEARNSENSE_REQUIRE_PG=1 but DATABASE_URL is not configured."
            )

        from backend.db.schema_check import ensure_required_migrations
        from backend.services.institution_service import _await_background

        # Fail startup on connection or pool initialization errors rather than
        # accepting traffic with an unusable PostgreSQL configuration.
        pool = await _await_background(get_pg_pool())
        # ...and on missing migrations (read-only check; nothing is applied).
        await _await_background(ensure_required_migrations(pool))
        pg_schema = {"status": "OK"}
    else:
        from backend.db.pg_connection import is_pg_configured

        if is_pg_configured():
            pg_schema = await _optional_pg_schema_status()

    logger.info("Running startup preflight checks...")
    _preflight_results = _run_startup_preflight()
    if pg_schema is not None:
        # Only present when PostgreSQL is configured, so JSON-mode health is unchanged.
        _preflight_results["postgres_schema"] = pg_schema
    for subsystem, result in _preflight_results.items():
        st = result.get("status", "UNKNOWN")
        if st == "OK":
            logger.info("Preflight [%s]: %s", subsystem, st)
        elif st == "DISABLED_BY_CONFIG":
            logger.info("Preflight [%s]: %s — %s", subsystem, st, result.get("reason", ""))
        else:
            logger.warning("Preflight [%s]: %s — %s", subsystem, st, result.get("reason", ""))


@app.on_event("shutdown")
async def on_shutdown():
    """Close the asyncpg pool on the persistent event loop that owns it."""
    from backend.db.pg_connection import is_pg_configured, close_pg_pool

    if is_pg_configured():
        from backend.services.institution_service import _run_async

        try:
            _run_async(close_pg_pool())
        except Exception:
            logger.exception("Failed to close institutional PostgreSQL pool")


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
    results = _preflight_results or {"_": {"status": "NOT_IMPLEMENTED", "reason": "Preflight not yet run"}}
    if is_strict():
        # Unauthenticated endpoint: in staging/production expose status only, not
        # exception text, provider names or versions.
        results = {name: {"status": r.get("status", "UNKNOWN")} for name, r in results.items()}
    return {"subsystems": results}
