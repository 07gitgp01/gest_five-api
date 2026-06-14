import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import ChangePasswordRequest, UserResponse, UserUpdate
from app.services.user_service import UserService

router = APIRouter()


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Profil connecté",
)
async def get_me(current_user: User = Depends(get_current_active_user)):
    return current_user


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Mise à jour du profil",
)
async def update_me(
    data: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await UserService(db).update_me(current_user, data)


@router.post(
    "/me/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Changement de mot de passe",
)
async def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await UserService(db).change_password(current_user, data)


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Désactivation du compte",
    description="Désactive le compte de l'utilisateur connecté. Action irréversible sans admin.",
)
async def deactivate_me(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await UserService(db).deactivate_me(current_user)


# ── Admin ──────────────────────────────────────────────────────────────────────

@router.get(
    "/",
    response_model=list[UserResponse],
    summary="[Admin] Liste des utilisateurs",
)
async def list_users(
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await UserService(db).list_users(current_user, skip=skip, limit=limit)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="[Admin] Désactivation d'un compte",
)
async def deactivate_user(
    user_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await UserService(db).deactivate_user(current_user, user_id)
