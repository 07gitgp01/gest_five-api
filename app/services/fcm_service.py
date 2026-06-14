"""
Firebase Cloud Messaging — service d'envoi de notifications push.

Mode développement (FIREBASE_ENABLED=false) : log uniquement, simule un succès.
Mode production (FIREBASE_ENABLED=true)     : HTTP v1 API FCM avec OAuth2.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GUIDE D'ACTIVATION (production)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Firebase Console → Paramètres du projet → Comptes de service
   → Générer une nouvelle clé privée → télécharger serviceAccountKey.json
2. pip install google-auth httpx
3. Variables d'environnement (.env) :
      FIREBASE_ENABLED=true
      FIREBASE_PROJECT_ID=your-firebase-project-id
      FIREBASE_CREDENTIALS_PATH=/path/to/serviceAccountKey.json
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Structure d'un message FCM v1 :
{
    "message": {
        "token": "<device_fcm_token>",
        "notification": {"title": "...", "body": "..."},
        "data": {                           # paires clé/valeur string uniquement
            "type": "reservation_confirmed",
            "reservation_id": "uuid-..."
        },
        "android": {"priority": "high"},
        "apns": {"headers": {"apns-priority": "10"}}
    }
}
"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class FCMService:

    async def send(
        self,
        token: str,
        title: str,
        body: str,
        data: dict | None = None,
        notification_type: str = "",
    ) -> bool:
        """
        Envoie une notification push.
        N'émet jamais d'exception — les erreurs FCM ne doivent pas
        interrompre le flux métier (paiement, annulation…).
        """
        if not token:
            return False

        if not settings.FIREBASE_ENABLED:
            logger.info(
                "[FCM-DEV] token=%.8s… | type=%s | %s",
                token,
                notification_type,
                title,
            )
            return True

        return await self._send_http_v1(token, title, body, data or {}, notification_type)

    async def _send_http_v1(
        self,
        token: str,
        title: str,
        body: str,
        data: dict,
        notification_type: str,
    ) -> bool:
        """Envoi réel via l'API FCM HTTP v1 (nécessite google-auth + httpx)."""
        try:
            import httpx
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(
                settings.FIREBASE_CREDENTIALS_PATH,
                scopes=["https://www.googleapis.com/auth/firebase.messaging"],
            )
            creds.refresh(Request())

            payload = {
                "message": {
                    "token": token,
                    "notification": {"title": title, "body": body},
                    "data": {
                        "type": notification_type,
                        **{k: str(v) for k, v in data.items()},
                    },
                    "android": {"priority": "high"},
                    "apns": {"headers": {"apns-priority": "10"}},
                }
            }
            url = (
                f"https://fcm.googleapis.com/v1/projects/"
                f"{settings.FIREBASE_PROJECT_ID}/messages:send"
            )
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {creds.token}",
                        "Content-Type": "application/json",
                    },
                )
            if resp.status_code == 200:
                return True
            logger.warning("[FCM] Échec %s: %s", resp.status_code, resp.text[:200])
            return False

        except Exception as exc:
            logger.error("[FCM] Erreur inattendue: %s", exc)
            return False
