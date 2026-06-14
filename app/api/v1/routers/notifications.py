import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Page
from app.schemas.notification import (
    BulkReadResult,
    FcmTokenRegister,
    NotificationResponse,
    ReminderResult,
    UnreadCount,
)
from app.services.notification_service import NotificationService

router = APIRouter()


# ── Routes statiques AVANT les routes dynamiques /{id} ───────────────────────

@router.get(
    "/unread-count",
    response_model=UnreadCount,
    summary="Nombre de notifications non-lues",
)
async def get_unread_count(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await NotificationService(db).get_unread_count(current_user)


@router.patch(
    "/read-all",
    response_model=BulkReadResult,
    summary="Marquer toutes les notifications comme lues",
)
async def mark_all_read(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await NotificationService(db).mark_all_read(current_user)


@router.post(
    "/fcm-token",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Enregistrer / mettre à jour le token FCM",
    description=(
        "L'application mobile appelle cet endpoint au démarrage ou lorsque "
        "Firebase renouvelle le token. Un seul token par utilisateur (dernier écrasé)."
    ),
)
async def register_fcm_token(
    data: FcmTokenRegister,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await NotificationService(db).register_fcm_token(current_user, data.token)


@router.post(
    "/send-reminders",
    response_model=ReminderResult,
    summary="Déclencher les rappels de match (cron/admin)",
    description=(
        "Envoie les notifications MATCH_REMINDER pour les réservations CONFIRMED "
        "qui commencent dans les 30–90 prochaines minutes. "
        "Idempotent. Réservé aux administrateurs — appeler via cron job ou tâche planifiée."
    ),
)
async def send_reminders(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await NotificationService(db).send_match_reminders()


# ── Liste ─────────────────────────────────────────────────────────────────────

@router.get(
    "/",
    response_model=Page[NotificationResponse],
    summary="Mes notifications",
)
async def list_notifications(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    unread_only: bool = Query(default=False),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await NotificationService(db).list_my(
        current_user, skip=skip, limit=limit, unread_only=unread_only
    )


# ── Routes dynamiques /{id} ───────────────────────────────────────────────────

@router.patch(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Marquer une notification comme lue",
)
async def mark_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await NotificationService(db).mark_read(current_user, notification_id)


@router.delete(
    "/{notification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une notification",
)
async def delete_notification(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await NotificationService(db).delete(current_user, notification_id)
