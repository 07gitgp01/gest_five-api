import uuid

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository

security = HTTPBearer()


# ── Authentification ───────────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access" or not payload.get("sub"):
        raise UnauthorizedException("Token invalide ou expiré")

    try:
        user_id = uuid.UUID(payload["sub"])
    except ValueError:
        raise UnauthorizedException("Token invalide")

    user = await UserRepository(db).get(user_id)
    if not user:
        raise UnauthorizedException("Utilisateur introuvable")
    if not user.is_active:
        raise UnauthorizedException("Compte désactivé")
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    return current_user


async def require_owner_or_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role not in (UserRole.OWNER, UserRole.ADMIN):
        raise ForbiddenException("Réservé aux propriétaires de terrain")
    return current_user


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != UserRole.ADMIN:
        raise ForbiddenException("Accès réservé aux administrateurs")
    return current_user


# ── Pagination ─────────────────────────────────────────────────────────────────

class PaginationParams:
    def __init__(
        self,
        skip: int = Query(default=0, ge=0, description="Éléments à ignorer"),
        limit: int = Query(default=20, ge=1, le=100, description="Éléments par page"),
    ):
        self.skip = skip
        self.limit = limit
