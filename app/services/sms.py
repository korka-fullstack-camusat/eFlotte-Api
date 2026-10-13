"""
Envoi de SMS par l'Orange SMS API (https://developer.orange.com/apis/sms).

Configuration (.env) : ORANGE_CLIENT_ID, ORANGE_CLIENT_SECRET, ORANGE_SENDER_ADDRESS
(numéro d'envoi attribué par Orange, ex. tel:+2210000) et éventuellement ORANGE_SENDER_NAME.
Sans ORANGE_CLIENT_ID, les SMS sont désactivés : `sms_actif()` renvoie False.
"""
import re
import time
from urllib.parse import quote

import httpx

from ..config import settings

_TOKEN_URL = "https://api.orange.com/oauth/v3/token"
_SMS_URL = "https://api.orange.com/smsmessaging/v1/outbound/{sender}/requests"
_jeton: dict = {"valeur": None, "expire": 0.0}


class ErreurSMS(Exception):
    pass


def sms_actif() -> bool:
    return bool(settings.orange_client_id and settings.orange_client_secret)


def normaliser_telephone(brut) -> str | None:
    """Numéro au format international +221XXXXXXXXX (Sénégal par défaut).
    Accepte 77 123 45 67, 771234567, 221771234567, 00221…, +221…, et les autres
    indicatifs s'ils sont écrits avec + ou 00."""
    if brut is None:
        return None
    texte = str(brut).strip()
    if texte.endswith(".0"):               # nombre lu par Excel
        texte = texte[:-2]
    plus = texte.startswith("+")
    chiffres = re.sub(r"\D", "", texte)
    if not chiffres:
        return None
    if chiffres.startswith("00"):
        return "+" + chiffres[2:] if len(chiffres) > 10 else None
    if plus:
        return "+" + chiffres if len(chiffres) >= 10 else None
    if len(chiffres) == 9:                 # numéro sénégalais sans indicatif
        return "+221" + chiffres
    if len(chiffres) == 12 and chiffres.startswith("221"):
        return "+" + chiffres
    return None


def _obtenir_jeton(client: httpx.Client) -> str:
    if _jeton["valeur"] and _jeton["expire"] > time.time() + 60:
        return _jeton["valeur"]
    r = client.post(
        _TOKEN_URL,
        auth=(settings.orange_client_id, settings.orange_client_secret),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json"},
    )
    if r.status_code != 200:
        raise ErreurSMS(f"Authentification Orange refusée ({r.status_code})")
    data = r.json()
    _jeton["valeur"] = data["access_token"]
    _jeton["expire"] = time.time() + int(data.get("expires_in", 3000))
    return _jeton["valeur"]


def envoyer_sms(telephone: str, message: str, client: httpx.Client | None = None) -> None:
    """Envoie un SMS ; lève ErreurSMS avec un message lisible en cas d'échec."""
    if not sms_actif():
        raise ErreurSMS("SMS non configurés (ORANGE_CLIENT_ID absent)")
    propre = client is None
    client = client or httpx.Client(timeout=20)
    try:
        jeton = _obtenir_jeton(client)
        expediteur = settings.orange_sender_address
        corps = {
            "outboundSMSMessageRequest": {
                "address": f"tel:{telephone}",
                "senderAddress": expediteur,
                "outboundSMSTextMessage": {"message": message},
            }
        }
        if settings.orange_sender_name:
            corps["outboundSMSMessageRequest"]["senderName"] = settings.orange_sender_name
        r = client.post(
            _SMS_URL.format(sender=quote(expediteur, safe="")),
            json=corps,
            headers={"Authorization": f"Bearer {jeton}"},
        )
        if r.status_code not in (200, 201):
            try:
                detail = r.json().get("requestError", {})
                detail = next(iter(detail.values()), {}).get("text") or r.text
            except Exception:
                detail = r.text
            raise ErreurSMS(f"Refusé par Orange ({r.status_code}) : {str(detail)[:150]}")
    except httpx.HTTPError as e:
        raise ErreurSMS(f"Orange injoignable : {e.__class__.__name__}")
    finally:
        if propre:
            client.close()


def message_identifiants(username: str, mot_de_passe: str) -> str:
    """Texte sans accents (alphabet GSM : 1 SMS = 160 caractères au lieu de 70)."""
    lien = settings.app_url.rstrip("/") or "la plateforme eFlotte"
    return (
        f"eFlotte CAMUSAT: compte chauffeur cree. Lien: {lien} "
        f"Identifiant: {username} Mot de passe: {mot_de_passe} (a changer a la 1re connexion)"
    )
