"""
Envoi de SMS par Orange SMS Pro Sénégal.

Même méthode que la plateforme eRH (attendance/sms_service.py), qui fonctionne avec
les mêmes identifiants :
  - POST formulaire sur https://api.orangesmspro.sn:8443/api (sans « /json ») ;
  - champs token, subject (VIDE), signature, recipient (221XXXXXXXXX), content,
    timestamp, key, algo=hmac ;
  - key = HMAC-SHA1(ORANGE_SMS_ACCESS_KEY, token + "" + signature + recipient + content
    + timestamp), en hexadécimal, encodage UTF-8 ;
  - réponse : texte « STATUS_CODE: 200 » (endpoint /api) ou JSON (status_CODE 100 / 200).

Configuration (.env du serveur, jamais dans le code) :
  ORANGE_SMS_TOKEN, ORANGE_SMS_ACCESS_KEY, ORANGE_SMS_SIGNATURE (nom d'expéditeur
  autorisé, ex. « CAMUSAT SN »), ORANGE_SMS_BASE_URL, ORANGE_SMS_VERIFY_SSL.
  ORANGE_SMS_LOGIN n'est pas utilisé par l'envoi.
Sans ORANGE_SMS_TOKEN / ACCESS_KEY, les SMS sont désactivés.
"""
import hashlib
import hmac
import json
import logging
import re
import time

import httpx

from ..config import settings

log = logging.getLogger("eflotte.sms")


class ErreurSMS(Exception):
    pass


def url_envoi() -> str:
    """Adresse d'envoi : l'endpoint /api (une adresse se terminant par /json est ramenée à /api)."""
    url = settings.orange_sms_base_url.strip().rstrip("/")
    return url[:-5] if url.endswith("/json") else url


def resume_configuration() -> str:
    """Configuration SMS lue au démarrage (sans le token ni la clé)."""
    if not sms_actif():
        manquants = [n for n, v in (("ORANGE_SMS_TOKEN", settings.orange_sms_token),
                                    ("ORANGE_SMS_ACCESS_KEY", settings.orange_sms_access_key)) if not v]
        return f"SMS désactivés : {', '.join(manquants)} absent(s) du .env"
    return (f"SMS actifs : signature=« {settings.orange_sms_signature} » url={url_envoi()} "
            f"verify_ssl={settings.orange_sms_verify_ssl}")


def sms_actif() -> bool:
    return bool(settings.orange_sms_token and settings.orange_sms_access_key)


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


def generer_cle(token: str, signature: str, destinataire: str, contenu: str, horodatage: int, secret: str) -> str:
    """HMAC-SHA1 hexadécimal ; le sujet (vide) fait partie de la concaténation."""
    chaine = token + "" + signature + destinataire + contenu + str(horodatage)
    return hmac.new(secret.encode("utf-8"), chaine.encode("utf-8"), hashlib.sha1).hexdigest()


def _lire_reponse(texte: str) -> tuple[bool, int | None]:
    """(succès, code Orange) : réponse texte « STATUS_CODE: 200 » (/api) ou JSON (/api/json)."""
    if texte.lstrip().startswith("{"):
        try:
            data = json.loads(texte)
        except ValueError:
            return False, None
        reponses = (data.get("responses") or {}).get("response") or data.get("response") or []
        if isinstance(reponses, dict):
            reponses = [reponses]
        if reponses:
            premier = reponses[0]
            statut = premier.get("status") if isinstance(premier.get("status"), dict) else premier
            code = statut.get("status_CODE", statut.get("status_code"))
            try:
                code = int(code)
            except (TypeError, ValueError):
                return False, None
            return code in (100, 200), code
        return False, None
    m = re.search(r"STATUS_CODE:\s*(\d+)", texte, re.IGNORECASE)
    if m:
        code = int(m.group(1))
        return code == 200, code
    return False, None


def _texte_erreur(texte: str) -> str:
    """Message d'Orange lisible (STATUS_TEXT / status_text), sinon le début de la réponse."""
    m = re.search(r'status_TEXT"?\s*[:=]\s*"?([^"<\n}]+)', texte, re.IGNORECASE)
    return (m.group(1).strip() if m else re.sub(r"<[^>]+>", " ", texte).strip())[:300]


def envoyer_sms(telephone: str, message: str, client: httpx.Client | None = None,
                sujet: str = "") -> str:
    """Envoie un SMS. Renvoie la réponse brute d'Orange ; lève ErreurSMS avec un message
    lisible en cas d'échec. `sujet` est ignoré : Orange exige un sujet vide (clé)."""
    if not sms_actif():
        raise ErreurSMS("SMS non configurés (ORANGE_SMS_TOKEN / ACCESS_KEY absents)")
    destinataire = re.sub(r"\D", "", telephone)
    horodatage = int(time.time())
    champs = {
        "token": settings.orange_sms_token,
        "subject": "",                       # vide : requis par le calcul de la clé
        "signature": settings.orange_sms_signature,
        "recipient": destinataire,
        "content": message,
        "timestamp": str(horodatage),
        "key": generer_cle(settings.orange_sms_token, settings.orange_sms_signature, destinataire,
                           message, horodatage, settings.orange_sms_access_key),
        "algo": "hmac",
    }
    propre = client is None
    client = client or client_sms()
    try:
        r = client.post(url_envoi(), data=champs)
    except httpx.HTTPError as e:
        cause = str(e).strip() or e.__class__.__name__
        if "CERTIFICATE_VERIFY_FAILED" in cause or "SSL" in cause.upper():
            cause += " — certificat du serveur Orange refusé (essayer ORANGE_SMS_VERIFY_SSL=False)"
        log.warning("SMS vers %s : échec de connexion à %s : %s", destinataire[:5] + "…", url_envoi(), cause)
        raise ErreurSMS(f"Orange SMS Pro injoignable : {e.__class__.__name__} : {cause[:300]}")
    finally:
        if propre:
            client.close()
    succes, code = _lire_reponse(r.text)
    if succes:
        log.info("SMS envoyé vers %s (code %s)", destinataire[:5] + "…", code)
        return r.text[:1000]
    log.warning("SMS vers %s refusé : HTTP %s code %s %s", destinataire[:5] + "…", r.status_code, code, r.text[:800])
    raise ErreurSMS(f"Refusé par Orange (HTTP {r.status_code}, code {code}) : {_texte_erreur(r.text)}")


def client_sms() -> httpx.Client:
    """Client HTTP réutilisable pour un envoi en série."""
    return httpx.Client(timeout=30, verify=settings.orange_sms_verify_ssl)


def message_identifiants(username: str, mot_de_passe: str) -> str:
    """SMS envoyé à la création d'un compte chauffeur (et par « Envoyer les identifiants »).
    Les accents utilisés (é, è, à) font partie de l'alphabet SMS standard (GSM 03.38)."""
    return (
        "Bonjour,\n"
        "Votre compte eFlotte a été créé avec succès.\n"
        "Vos identifiants de connexion :\n"
        f"- Identifiant : {username}\n"
        f"- Mot de passe : {mot_de_passe}\n"
        "Important : Pour des raisons de sécurité, veuillez modifier votre mot de passe "
        "dès votre première connexion.\n"
        "Bienvenue sur eFlotte !"
    )
