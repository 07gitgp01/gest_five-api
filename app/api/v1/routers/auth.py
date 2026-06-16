from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, mask_phone
from app.db.session import get_db
from app.schemas.token import Token
from app.schemas.user import UserLogin, UserRegister
from app.services.auth_service import AuthService

router = APIRouter()
logger = get_logger("gestfive.auth")


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post(
    "/register",
    response_model=Token,
    status_code=201,
    summary="Inscription",
    description="Crée un compte et retourne une paire access/refresh token.",
)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    try:
        token = await AuthService(db).register(data)
        logger.info(
            "REGISTER ok — phone=%s role=%s",
            mask_phone(data.phone),
            getattr(data, "role", "player"),
        )
        return token
    except HTTPException as exc:
        logger.warning(
            "REGISTER rejeté — phone=%s code=%d detail=%s",
            mask_phone(data.phone),
            exc.status_code,
            exc.detail,
        )
        raise
    except Exception:
        logger.exception("REGISTER erreur inattendue — phone=%s", mask_phone(data.phone))
        raise


@router.post(
    "/login",
    response_model=Token,
    summary="Connexion",
    description="Authentifie par numéro de téléphone et retourne les tokens.",
)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    try:
        token = await AuthService(db).login(data)
        logger.info("LOGIN ok — phone=%s", mask_phone(data.phone))
        return token
    except HTTPException as exc:
        if exc.status_code == 401:
            logger.warning(
                "LOGIN refusé — phone=%s raison=identifiants invalides",
                mask_phone(data.phone),
            )
        else:
            logger.warning(
                "LOGIN rejeté — phone=%s code=%d",
                mask_phone(data.phone),
                exc.status_code,
            )
        raise
    except Exception:
        logger.exception("LOGIN erreur inattendue — phone=%s", mask_phone(data.phone))
        raise


@router.post(
    "/refresh",
    response_model=Token,
    summary="Rafraîchissement des tokens",
    description="Échange un refresh token valide contre une nouvelle paire de tokens.",
)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        token = await AuthService(db).refresh_tokens(data.refresh_token)
        logger.debug("REFRESH ok")
        return token
    except HTTPException as exc:
        logger.warning("REFRESH rejeté — code=%d %s", exc.status_code, exc.detail)
        raise
    except Exception:
        logger.exception("REFRESH erreur inattendue")
        raise
