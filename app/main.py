from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.routers import auth, users, terrains, reservations
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.session import check_db_connection, init_db

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


def create_application() -> FastAPI:
    application = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description="API backend pour la plateforme GestFive de réservation de terrains de football à 5.",
        docs_url="/api/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url="/api/redoc" if settings.ENVIRONMENT != "production" else None,
        openapi_url="/api/openapi.json" if settings.ENVIRONMENT != "production" else None,
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if settings.ENVIRONMENT == "production":
        application.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.ALLOWED_HOSTS,
        )

    application.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
    application.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
    application.include_router(terrains.router, prefix="/api/v1/terrains", tags=["Terrains"])
    application.include_router(reservations.router, prefix="/api/v1/reservations", tags=["Reservations"])

    return application


app = create_application()


@app.get("/", tags=["Health"])
async def root():
    return {"message": "GestFive API", "version": settings.VERSION, "status": "ok"}


@app.get("/health", tags=["Health"])
async def health_check():
    db_ok = await check_db_connection()
    status = "healthy" if db_ok else "degraded"
    return {"status": status, "database": "up" if db_ok else "down"}
