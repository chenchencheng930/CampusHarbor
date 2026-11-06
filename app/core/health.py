from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def readiness_report(db: Session, settings: Any) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"status": "UP"}
    except Exception as exc:  # pragma: no cover - driver-specific
        checks["database"] = {"status": "DOWN", "error": type(exc).__name__}

    redis_status = "DISABLED"
    if getattr(settings, "redis_url", ""):
        try:
            from app.services.memory import RedisShortTermMemoryStore

            store = RedisShortTermMemoryStore(settings)
            redis_status = "UP" if store.client is not None and store.client.ping() else "DOWN"
        except Exception:
            redis_status = "DEGRADED"
    checks["redis"] = {"status": redis_status}
    checks["ai"] = {
        "status": "CONFIGURED" if getattr(settings, "ai_provider", "mock") == "mock" or getattr(settings, "openai_api_key", "") or getattr(settings, "ollama_base_url", "") else "MISSING_CONFIG",
        "provider": getattr(settings, "ai_provider", "mock"),
    }
    overall = "UP" if all(item["status"] in {"UP", "DISABLED", "CONFIGURED"} for item in checks.values()) else "DEGRADED"
    return {"status": overall, "timestamp": datetime.now(timezone.utc).isoformat(), "checks": checks}
