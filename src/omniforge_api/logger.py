# src/omniforge_api/logger.py
from __future__ import annotations
import logging
import structlog

def configure_logging(process_name: str) -> None:
    """Настройка структурного логирования для процесса."""
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() # Для разработки. В prod заменить на JSONRenderer
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(process=process_name)

def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)