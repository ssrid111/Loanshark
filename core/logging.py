"""Allowlisted JSON logs: never render arbitrary messages, SQL or exception text."""

import json
import logging
import traceback
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        # Only application-controlled event names are emitted, not third-party messages.
        data["event"] = getattr(record, "event", "library_event")
        for key in ("request_id", "method", "status_code", "error_type", "frames"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        library_logger = logging.getLogger(name)
        library_logger.handlers.clear()
        library_logger.propagate = True


def log_failure(logger: logging.Logger, event: str, exc: Exception, request_id: str) -> None:
    # Keep diagnostic code locations without exception messages, parameters, locals or SQL.
    frames = [f"{frame.name}:{frame.lineno}" for frame in traceback.extract_tb(exc.__traceback__)]
    logger.error(
        event,
        extra={
            "event": event,
            "request_id": request_id,
            "error_type": type(exc).__name__,
            "frames": frames,
        },
    )
