"""
Notifications des chauffeurs : enregistrées en base (affichées dans l'app et transformées en
notification du téléphone par l'app elle-même, sans Firebase), et envoyées en push distant
(service Expo) aux téléphones qui ont enregistré un jeton (APK construit avec EAS).
"""
import logging

import httpx
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models.demande import NotificationChauffeur, PushToken

log = logging.getLogger("eflotte.notifications")
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def notifier(db: Session, user_id: int, type_: str, titre: str, message: str | None = None,
             data: dict | None = None) -> NotificationChauffeur:
    """Ajoute une notification (commit fait par l'appelant)."""
    n = NotificationChauffeur(user_id=user_id, type=type_, titre=titre[:150], message=message, data=data or {})
    db.add(n)
    return n


def envoyer_push(user_ids: list[int], titre: str, message: str | None, data: dict | None = None) -> None:
    """Push distant via Expo (à lancer en tâche de fond). Silencieux si aucun jeton."""
    db = SessionLocal()
    try:
        jetons = [t for (t,) in db.query(PushToken.token).filter(PushToken.user_id.in_(user_ids)).all()]
        if not jetons:
            return
        messages = [{"to": j, "title": titre, "body": message or "", "data": data or {},
                     "sound": "default", "channelId": "default", "priority": "high"} for j in jetons]
        for i in range(0, len(messages), 100):          # Expo : 100 messages par requête au plus
            try:
                r = httpx.post(EXPO_PUSH_URL, json=messages[i:i + 100], timeout=15)
                tickets = (r.json() or {}).get("data") or []
                erreurs = [t for t in tickets if isinstance(t, dict) and t.get("status") == "error"]
                if erreurs:
                    # Ex. InvalidCredentials = clé FCM (Firebase) absente du projet EAS
                    log.warning("Push Expo : %d échec(s) — %s", len(erreurs),
                                "; ".join(f"{(t.get('details') or {}).get('error', '?')}: {t.get('message', '')}" for t in erreurs[:3]))
                else:
                    log.info("Push Expo envoyé à %d appareil(s)", len(messages[i:i + 100]))
                # Jetons devenus invalides (application désinstallée…) : on les oublie
                morts = [m["to"] for m, t in zip(messages[i:i + 100], tickets)
                         if isinstance(t, dict) and (t.get("details") or {}).get("error") == "DeviceNotRegistered"]
                if morts:
                    db.query(PushToken).filter(PushToken.token.in_(morts)).delete(synchronize_session=False)
                    db.commit()
            except (httpx.HTTPError, ValueError) as e:
                log.warning("Push Expo impossible : %s", e)
    finally:
        db.close()
