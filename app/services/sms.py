"""
Envoi de SMS par Orange SMS Pro Sénégal (https://api.orangesmspro.sn:8443).

Configuration (.env, jamais dans le code) :
  ORANGE_SMS_LOGIN, ORANGE_SMS_TOKEN, ORANGE_SMS_ACCESS_KEY,
  ORANGE_SMS_SIGNATURE (nom d'expéditeur, ex. « CAMUSAT NOC »),
  ORANGE_SMS_BASE_URL (ex. https://api.orangesmspro.sn:8443/api/json),
  ORANGE_SMS_VERIFY_SSL (True par défaut).
Sans ORANGE_SMS_LOGIN / TOKEN / ACCESS_KEY, les SMS sont désactivés.

Requête : POST (formulaire) avec authentification Basic login:token et les champs
token, subject, signature, recipient (221XXXXXXXXX), content, timestamp et key =
HMAC-SHA1(access_key, token + subject + signature + recipient + content + timestamp).
"""
import hashlib
import hmac
import logging
import re
import time

import httpx

from ..config import settings

log = logging.getLogger("eflotte.sms")


class ErreurSMS(Exception):
    pass


def sms_actif() -> bool:
    return bool(settings.orange_sms_login and settings.orange_sms_token and settings.orange_sms_access_key)


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


def _reponse_en_erreur(r: httpx.Response) -> str | None:
    """Message d'erreur si la réponse d'Orange signale un échec, sinon None."""
    if r.status_code >= 400:
        return f"HTTP {r.status_code} : {r.text[:200]}"
    try:
        data = r.json()
    except ValueError:
        return None if r.text.strip() else "Réponse vide"
    if isinstance(data, dict):
        statut = str(data.get("status", data.get("STATUS", ""))).upper()
        if data.get("error") or data.get("ERROR") or statut in ("ERROR", "FAILED", "KO"):
            return f"Refusé par Orange : {str(data)[:200]}"
    return None


def envoyer_sms(telephone: str, message: str, client: httpx.Client | None = None,
                sujet: str = "eFlotte") -> str:
    """Envoie un SMS. Renvoie la réponse brute d'Orange (tronquée) ; lève ErreurSMS
    avec un message lisible en cas d'échec."""
    if not sms_actif():
        raise ErreurSMS("SMS non configurés (ORANGE_SMS_LOGIN / TOKEN / ACCESS_KEY absents)")
    destinataire = telephone.lstrip("+")
    token, signature = settings.orange_sms_token, settings.orange_sms_signature
    horodatage = str(int(time.time()))
    cle = hmac.new(
        settings.orange_sms_access_key.encode(),
        (token + sujet + signature + destinataire + message + horodatage).encode(),
        hashlib.sha1,
    ).hexdigest()
    champs = {
        "token": token, "subject": sujet, "signature": signature,
        "recipient": destinataire, "content": message,
        "timestamp": horodatage, "key": cle,
    }
    propre = client is None
    client = client or httpx.Client(timeout=30, verify=settings.orange_sms_verify_ssl)
    try:
        r = client.post(
            settings.orange_sms_base_url,
            data=champs,
            auth=(settings.orange_sms_login, token),
            headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as e:
        raise ErreurSMS(f"Orange SMS Pro injoignable : {e.__class__.__name__}")
    finally:
        if propre:
            client.close()
    erreur = _reponse_en_erreur(r)
    log.info("SMS vers %s : HTTP %s %s", destinataire[:5] + "…", r.status_code, r.text[:200])
    if erreur:
        raise ErreurSMS(erreur)
    return r.text[:300]


def client_sms() -> httpx.Client:
    """Client HTTP réutilisable pour un envoi en série."""
    return httpx.Client(timeout=30, verify=settings.orange_sms_verify_ssl)


def message_identifiants(username: str, mot_de_passe: str) -> str:
    """Texte sans accents (alphabet GSM : 1 SMS = 160 caractères au lieu de 70)."""
    lien = settings.app_url.rstrip("/") or "la plateforme eFlotte"
    return (
        f"eFlotte CAMUSAT: compte chauffeur cree. Lien: {lien} "
        f"Identifiant: {username} Mot de passe: {mot_de_passe} (a changer a la 1re connexion)"
    )
