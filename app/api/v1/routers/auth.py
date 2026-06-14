from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.token import Token
from app.schemas.user import UserLogin, UserRegister
from app.services.auth_service import AuthService

router = APIRouter()


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
    return await AuthService(db).register(data)


@router.post(
    "/login",
    response_model=Token,
    summary="Connexion",
    description="Authentifie par numéro de téléphone et retourne les tokens.",
)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    return await AuthService(db).login(data)


@router.post(
    "/refresh",
    response_model=Token,
    summary="Rafraîchissement des tokens",
    description="Échange un refresh token valide contre une nouvelle paire de tokens.",
)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    return await AuthService(db).refresh_tokens(data.refresh_token)
