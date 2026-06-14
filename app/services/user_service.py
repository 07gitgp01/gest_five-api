import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.core.security import hash_password, verify_password
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.user import ChangePasswordRequest, UserUpdate


class UserService:
    def __init__(self, db: AsyncSession):
        self.repo = UserRepository(db)

    async def get_me(self, user_id: uuid.UUID) -> User:
        user = await self.repo.get(user_id)
        if not user:
            raise NotFoundException("Utilisateur introuvable")
        return user

    async def update_me(self, user: User, data: UserUpdate) -> User:
        return await self.repo.update(user, data.model_dump(exclude_none=True))

    async def change_password(self, user: User, data: ChangePasswordRequest) -> None:
        if not verify_password(data.current_password, user.hashed_password):
            raise BadRequestException("Mot de passe actuel incorrect")
        if data.current_password == data.new_password:
            raise BadRequestException("Le nouveau mot de passe doit être différent de l'actuel")
        await self.repo.update(user, {"hashed_password": hash_password(data.new_password)})

    async def deactivate_me(self, user: User) -> User:
        return await self.repo.update(user, {"is_active": False})

    async def deactivate_user(self, admin: User, target_id: uuid.UUID) -> User:
        if admin.role != UserRole.ADMIN:
            raise ForbiddenException("Accès réservé aux administrateurs")
        if admin.id == target_id:
            raise BadRequestException("Utilisez /me pour désactiver votre propre compte")
        user = await self.repo.get(target_id)
        if not user:
            raise NotFoundException("Utilisateur introuvable")
        return await self.repo.update(user, {"is_active": False})

    async def list_users(self, admin: User, skip: int = 0, limit: int = 20) -> list[User]:
        if admin.role != UserRole.ADMIN:
            raise ForbiddenException("Accès réservé aux administrateurs")
        return await self.repo.get_all(skip=skip, limit=limit)
