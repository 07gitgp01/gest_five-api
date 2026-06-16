import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

from app.core.config import settings

# ── Propagation du request_id dans les logs async ─────────────────────────────
# Initialisé par le middleware HTTP avant chaque requête ;
# tous les loggers appelés dans le même contexte asyncio héritent de la valeur.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def mask_phone(phone: str) -> str:
    """Remplace les 4 derniers chiffres par **** pour ne pas exposer les numéros dans les logs."""
    return phone[:-4] + "****" if len(phone) >= 4 else "****"


class _RequestContextFilter(logging.Filter):
    """Injecte automatiquement request_id dans chaque LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


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
        # Champs contextuels injectés par _RequestContextFilter et les middlewares
        for key in ("request_id", "method", "path", "status_code", "duration_ms"):
            if hasattr(record, key):
                obj[key] = getattr(record, key)
        return json.dumps(obj, ensure_ascii=False)


def _parse_level(level_str: str) -> int:
    """Convertit la chaîne LOG_LEVEL en constante logging (défaut : INFO)."""
    return getattr(logging, level_str.upper(), logging.INFO)


def setup_logging() -> None:
    level = _parse_level(settings.LOG_LEVEL)
    # En mode DEBUG explicite, forcer le niveau même si LOG_LEVEL ne l'indique pas
    if settings.DEBUG:
        level = min(level, logging.DEBUG)

    ctx_filter = _RequestContextFilter()

    if settings.ENVIRONMENT == "production":
        handler: logging.Handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JSONFormatter())
        fmt = "%(message)s"
    else:
        from rich.console import Console
        from rich.logging import RichHandler

        handler = RichHandler(
            console=Console(),
            rich_tracebacks=True,
            show_path=settings.DEBUG,
        )
        fmt = "%(message)s"

    handler.addFilter(ctx_filter)

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="[%X]",
        handlers=[handler],
        force=True,  # remplace les handlers enregistrés par uvicorn
    )

    # Silence les loggers trop verbeux par défaut
    for name in ("uvicorn.access", "sqlalchemy.engine", "httpx"):
        logging.getLogger(name).setLevel(
            logging.DEBUG if settings.DEBUG else logging.WARNING
        )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
