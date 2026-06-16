import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, UnauthorizedException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.repositories.user_repository import UserRepository
from app.schemas.token import Token
from app.schemas.user import UserLogin, UserRegister


class AuthService:
    def __init__(self, db: AsyncSession):
        self.repo = UserRepository(db)

    async def register(self, data: UserRegister) -> Token:
        # Vérifications séquentielles explicites pour retourner le bon message
        if await self.repo.phone_exists(data.phone):
            raise ConflictException("Un compte avec ce numéro existe déjà")
        if data.email and await self.repo.email_exists(data.email):
            raise ConflictException("Un compte avec cet email existe déjà")

        try:
            user = await self.repo.create({
                "firstname": data.firstname,
                "lastname": data.lastname,
                "phone": data.phone,
                "email": data.email,
                "role": data.role,
                "hashed_password": hash_password(data.password),
            })
        except IntegrityError:
            # Deux inscriptions concurrentes avec le même numéro/email →
            # la contrainte UNIQUE de la DB se déclenche ; retourne 409 propre.
            raise ConflictException(
                "Un compte avec ce numéro ou cet email existe déjà"
            )

        return Token(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        )

    async def login(self, data: UserLogin) -> Token:
        identifier = data.phone.strip()
        if "@" in identifier:
            user = await self.repo.get_by_email(identifier.lower())
        else:
            user = await self.repo.get_by_phone(identifier)

        # Vérification en temps constant même si user est None —
        # empêche l'énumération de comptes par mesure du temps de réponse.
        password_ok = verify_password(data.password, user.hashed_password) if user else False

        if not user or not password_ok:
            raise UnauthorizedException("Identifiant ou mot de passe incorrect")
        if not user.is_active:
            raise UnauthorizedException("Compte désactivé")

        # Rehash transparent si les paramètres Argon2 ont évolué
        if needs_rehash(user.hashed_password):
            await self.repo.update(user, {"hashed_password": hash_password(data.password)})

        return Token(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        )

    async def refresh_tokens(self, refresh_token: str) -> Token:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh" or not payload.get("sub"):
            raise UnauthorizedException("Token de rafraîchissement invalide")

        try:
            user_id = uuid.UUID(payload["sub"])
        except ValueError:
            raise UnauthorizedException("Token de rafraîchissement invalide")

        user = await self.repo.get(user_id)
        if not user or not user.is_active:
            raise UnauthorizedException("Utilisateur introuvable ou inactif")

        return Token(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        )
