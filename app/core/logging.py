import json
import logging
import sys
from datetime import datetime, timezone

from app.core.config import settings


class _JSONFormatter(logging.Formatter):
    """
    Formatter JSON structuré pour la production.
    Compatible avec Render, Datadog, CloudWatch et tout agrégateur qui lit stdout.
    """

    def format(self, record: logging.LogRecord) -> str:
        obj: dict = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            obj["exception"] = self.formatException(record.exc_info)
        # Champs contextuels optionnels ajoutés par les middlewares
        for key in ("request_id", "method", "path", "status_code", "duration_ms"):
            if hasattr(record, key):
                obj[key] = getattr(record, key)
        return json.dumps(obj, ensure_ascii=False)


def setup_logging() -> None:
    level = logging.DEBUG if settings.DEBUG else logging.INFO

    if settings.ENVIRONMENT == "production":
        # Logs JSON vers stdout — capturés par Render / tout agrégateur
        handler: logging.Handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JSONFormatter())
        fmt = "%(message)s"
    else:
        # Logs Rich colorés pour le développement local
        from rich.console import Console
        from rich.logging import RichHandler
        handler = RichHandler(
            console=Console(),
            rich_tracebacks=True,
            show_path=settings.DEBUG,
        )
        fmt = "%(message)s"

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="[%X]",
        handlers=[handler],
        force=True,    # remplace les handlers éventuellement enregistrés par uvicorn
    )

    # Silence les loggers trop verbeux
    for name in ("uvicorn.access", "sqlalchemy.engine", "httpx"):
        logging.getLogger(name).setLevel(
            logging.DEBUG if settings.DEBUG else logging.WARNING
        )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
