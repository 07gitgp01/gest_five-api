import logging
import time
import uuid as uuid_lib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.routers import (
    admin,
    auth,
    dashboard,
    notifications,
    owner_dashboard,
    payments,
    reservations,
    terrains,
    time_slots,
    users,
)
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.session import check_db_connection, init_db

setup_logging()

logger = logging.getLogger(__name__)

# Timestamp de démarrage — utilisé par /health pour calculer l'uptime
_START_TIME: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _START_TIME
    _START_TIME = time.time()
    await init_db()
    logger.info(
        "GestFive API démarré | version=%s environnement=%s",
        settings.VERSION,
        settings.ENVIRONMENT,
    )
    yield
    logger.info("GestFive API arrêté proprement.")


def create_application() -> FastAPI:
    application = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=(
            "API backend pour la plateforme GestFive de réservation "
            "de terrains de football à 5."
        ),
        docs_url="/api/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url="/api/redoc" if settings.ENVIRONMENT != "production" else None,
        openapi_url="/api/openapi.json" if settings.ENVIRONMENT != "production" else None,
        lifespan=lifespan,
    )

    # ── Middlewares ───────────────────────────────────────────────────────────

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    if settings.ENVIRONMENT == "production":
        application.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.ALLOWED_HOSTS,
        )

    # ── Middleware : logging des requêtes + X-Request-ID ─────────────────────

    @application.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        request_id = str(uuid_lib.uuid4())[:8]
        start = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s → %d (%.0f ms) [%s]",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        response.headers["X-Request-ID"] = request_id
        return response

    # ── Gestionnaires d'erreurs globaux ───────────────────────────────────────

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors(include_url=False)
        # Pydantic v2 stocke l'objet Exception dans ctx['error'] — pas JSON-sérialisable
        for error in errors:
            if "ctx" in error:
                error["ctx"] = {
                    k: str(v) if isinstance(v, Exception) else v
                    for k, v in error["ctx"].items()
                }
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"message": "Données invalides", "detail": errors},
        )

    @application.exception_handler(SQLAlchemyError)
    async def db_error_handler(
        request: Request, exc: SQLAlchemyError
    ) -> JSONResponse:
        logger.exception("Erreur base de données non gérée : %s", exc)
        detail = str(exc) if settings.DEBUG else "Erreur base de données — réessayez dans quelques instants."
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"message": "Service temporairement indisponible", "detail": detail},
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(
            "Exception non gérée sur %s %s : %s",
            request.method,
            request.url.path,
            exc,
        )
        detail = str(exc) if settings.DEBUG else "Une erreur inattendue s'est produite."
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "message": "Erreur interne du serveur",
                "detail": detail,
            },
        )

    # ── Routeurs ──────────────────────────────────────────────────────────────

    application.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
    application.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
    application.include_router(terrains.router, prefix="/api/v1/terrains", tags=["Terrains"])
    application.include_router(reservations.router, prefix="/api/v1/reservations", tags=["Reservations"])
    # time_slots monté sur /terrains pour les URLs imbriquées /{terrain_id}/slots
    application.include_router(time_slots.router, prefix="/api/v1/terrains", tags=["TimeSlots"])
    application.include_router(payments.router, prefix="/api/v1/payments", tags=["Payments"])
    application.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
    application.include_router(owner_dashboard.router, prefix="/api/v1/owner-dashboard", tags=["Owner Dashboard"])
    application.include_router(notifications.router, prefix="/api/v1/notifications", tags=["Notifications"])
    application.include_router(admin.router, prefix="/api/v1/admin", tags=["Administration"])

    return application


app = create_application()


# ── Endpoints racine ──────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
async def root():
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "ok",
        "docs": "/api/docs" if settings.ENVIRONMENT != "production" else None,
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check utilisé par Render (healthCheckPath) et le HEALTHCHECK Docker.
    Retourne 200 si l'API et la base de données sont opérationnelles, 503 sinon.
    """
    db_ok = await check_db_connection()
    uptime_s = int(time.time() - _START_TIME) if _START_TIME else 0

    payload = {
        "status": "healthy" if db_ok else "degraded",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "database": "up" if db_ok else "down",
        "uptime_seconds": uptime_s,
    }

    if not db_ok:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload,
        )

    return payload
