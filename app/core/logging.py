import logging
import sys

from rich.console import Console
from rich.logging import RichHandler

from app.core.config import settings

console = Console()


def setup_logging() -> None:
    level = logging.DEBUG if settings.DEBUG else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                show_path=settings.DEBUG,
            )
        ],
    )

    # Silence noisy third-party loggers
    for logger_name in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(logger_name).setLevel(
            logging.DEBUG if settings.DEBUG else logging.WARNING
        )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
