import logging
import sys
from typing import TextIO

import structlog

from app.core.telemetry import current_ids


def _add_trace_ids(
    logger: object, method: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    for key, value in current_ids().items():
        event_dict.setdefault(key, value)
    return event_dict


def configure_logging(
    level: str = "INFO", stream: TextIO = sys.stdout, service: str | None = None
) -> None:
    """Route stdlib and structlog output through a single JSON renderer.

    Every line carries the context variables bound with `structlog.contextvars` (`run_id`,
    `node`, `request_id`) and, inside a span, `trace_id` and `span_id`.
    """

    def add_service(
        logger: object, method: str, event_dict: structlog.types.EventDict
    ) -> structlog.types.EventDict:
        if service:
            event_dict.setdefault("service", service)
        return event_dict

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        add_service,
        _add_trace_ids,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "arq"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
