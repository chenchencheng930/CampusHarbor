from pathlib import Path
import time
import logging
import threading

from fastapi import FastAPI
from fastapi import Request
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.bootstrap import create_schema, seed_data
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.tool_queue import get_tool_queue_worker
from app.services.ai import AiClient
from app.core.request_context import get_request_id, new_request_id, request_id_var


logger = logging.getLogger(__name__)


def _warmup_ai_model() -> None:
    settings = get_settings()
    try:
        AiClient(settings).warmup()
        logger.info("Ollama model warmup completed: %s", settings.ollama_model)
    except Exception:
        logger.warning("Ollama model warmup failed; the first chat request will load it", exc_info=True)


def create_app() -> FastAPI:
    app = FastAPI(title="MindBridge Python", version="0.1.0")

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time-Ms"] = str(round((time.perf_counter() - started) * 1000, 2))
            return response
        finally:
            request_id_var.reset(token)

    @app.middleware("http")
    async def no_cache_frontend_assets(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/api/") or path.endswith((".html", ".js", ".css")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.on_event("startup")
    def startup() -> None:
        create_schema()
        db = SessionLocal()
        try:
            seed_data(db)
        finally:
            db.close()
        worker = get_tool_queue_worker(get_settings())
        worker.start()
        app.state.tool_queue_worker = worker
        settings = get_settings()
        if settings.ollama_warmup_enabled and settings.ai_provider.lower() == "ollama":
            threading.Thread(target=_warmup_ai_model, name="ollama-warmup", daemon=True).start()

    @app.on_event("shutdown")
    def shutdown() -> None:
        worker = getattr(app.state, "tool_queue_worker", None)
        if worker is not None:
            worker.stop()

    app.include_router(router)
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


app = create_app()
