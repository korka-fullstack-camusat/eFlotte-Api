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


def resume_configuration() -> str:
    """Configuration SMS lue au démarrage (sans le token ni la clé)."""
    if not sms_actif():
        manquants = [n for n, v in (("ORANGE_SMS_LOGIN", settings.orange_sms_login),
                                    ("ORANGE_SMS_TOKEN", settings.orange_sms_token),
                                    ("ORANGE_SMS_ACCESS_KEY", settings.orange_sms_access_key)) if not v]
        return f"SMS désactivés : {', '.join(manquants)} absent(s) du .env"
    return (f"SMS actifs : login={settings.orange_sms_login} signature=« {settings.orange_sms_signature} » "
            f"url={settings.orange_sms_base_url} verify_ssl={settings.orange_sms_verify_ssl}")


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


CODES_SUCCES = {0, 200}
CODE_CLE_INVALIDE = 121


def _statuts_orange(data) -> list[tuple[int | None, str]]:
    """(code, texte) de chaque « status » trouvé dans la réponse JSON d'Orange
    ({"responses": {"response": [{"status": {"status_CODE": 121, "status_TEXT": …}}]}})."""
    trouves: list[tuple[int | None, str]] = []

    def parcourir(v):
        if isinstance(v, dict):
            bas = {str(k).lower(): val for k, val in v.items()}
            if "status_code" in bas:
                try:
                    code = int(bas["status_code"])
                except (TypeError, ValueError):
                    code = None
                trouves.append((code, str(bas.get("status_text") or "")))
            for val in v.values():
                parcourir(val)
        elif isinstance(v, list):
            for val in v:
                parcourir(val)

    parcourir(data)
    return trouves


def _reponse_en_erreur(r: httpx.Response) -> tuple[int | None, str] | None:
    """(code Orange, message) si la réponse signale un échec, sinon None.
    Orange répond HTTP 200 même en cas d'erreur : le code est dans status_CODE."""
    if r.status_code >= 400:
        return None, f"HTTP {r.status_code} : {r.text[:500]}"
    try:
        data = r.json()
    except ValueError:
        return None if r.text.strip() else (None, "Réponse vide d'Orange")
    for code, texte in _statuts_orange(data):
        if code is not None and code not in CODES_SUCCES:
            return code, f"Refusé par Orange (code {code}) : {texte}"
    if isinstance(data, dict):
        statut = str(data.get("status", data.get("STATUS", ""))).upper()
        if data.get("error") or data.get("ERROR") or statut in ("ERROR", "FAILED", "KO"):
            return None, f"Refusé par Orange : {str(data)[:500]}"
    return None


# Calcul de la clé (paramètre « key ») et format d'envoi : Orange ne publie pas sa
# documentation. La 1re combinaison est la formule habituelle (HMAC-SHA1 de
# token+subject+signature+recipient+content+timestamp avec la clé d'accès), envoyée en
# formulaire. Si Orange répond 121 (« KEY invalide »), les combinaisons suivantes sont
# essayées une à une (une requête refusée n'envoie aucun SMS) ; celle qui est acceptée
# est retenue pour les envois suivants et écrite dans les logs.
_ORDRE = ("token", "subject", "signature", "recipient", "content", "timestamp")
# (nom, champs concaténés, secret, algorithme, paramètre algo, envoi)
#   algorithme : sha1 / md5 / sha256 = HMAC ; "md5-simple" = MD5 de (champs + clé d'accès)
#   envoi : "form" (formulaire POST), "json" (corps JSON POST), "query" (paramètres dans l'URL, POST)
VARIANTES_CLE = [
    ("hmac-sha1 / formulaire", _ORDRE, "access_key", "sha1", None, "form"),
    ("hmac-sha1 / json", _ORDRE, "access_key", "sha1", None, "json"),
    ("hmac-sha1 / url", _ORDRE, "access_key", "sha1", None, "query"),
    ("hmac-md5 / formulaire", _ORDRE, "access_key", "md5", "md5", "form"),
    ("hmac-md5 / json", _ORDRE, "access_key", "md5", "md5", "json"),
    ("md5-simple / formulaire", _ORDRE, "access_key", "md5-simple", "md5", "form"),
    ("hmac-sha1 secret=token / formulaire", _ORDRE, "token", "sha1", None, "form"),
    ("hmac-sha1 sans token / formulaire", _ORDRE[1:], "access_key", "sha1", None, "form"),
    ("hmac-sha1 login au lieu du token / formulaire",
     ("login",) + _ORDRE[1:], "access_key", "sha1", None, "form"),
]
_variante_retenue: int | None = None


def _champs(variante, destinataire: str, message: str, sujet: str) -> dict:
    _nom, ordre, secret, algo, param_algo, _envoi = variante
    valeurs = {
        "token": settings.orange_sms_token, "login": settings.orange_sms_login,
        "subject": sujet, "signature": settings.orange_sms_signature,
        "recipient": destinataire, "content": message, "timestamp": str(int(time.time())),
    }
    cle_secrete = settings.orange_sms_access_key if secret == "access_key" else settings.orange_sms_token
    a_signer = "".join(valeurs[c] for c in ordre)
    if algo == "md5-simple":
        cle = hashlib.md5((a_signer + cle_secrete).encode("utf-8")).hexdigest()
    else:
        cle = hmac.new(cle_secrete.encode("utf-8"), a_signer.encode("utf-8"), getattr(hashlib, algo)).hexdigest()
    champs = {k: valeurs[k] for k in _ORDRE}
    champs["key"] = cle
    if param_algo:
        champs["algo"] = param_algo
    return champs


def _poster(client: httpx.Client, variante, champs: dict) -> httpx.Response:
    envoi = variante[5]
    options = {
        "auth": (settings.orange_sms_login, settings.orange_sms_token),
        "headers": {"Accept": "application/json"},
    }
    if envoi == "json":
        return client.post(settings.orange_sms_base_url, json=champs, **options)
    if envoi == "query":
        return client.post(settings.orange_sms_base_url, params=champs, **options)
    return client.post(settings.orange_sms_base_url, data=champs, **options)


def envoyer_sms(telephone: str, message: str, client: httpx.Client | None = None,
                sujet: str = "eFlotte") -> str:
    """Envoie un SMS. Renvoie la réponse brute d'Orange ; lève ErreurSMS avec un
    message lisible en cas d'échec."""
    global _variante_retenue
    if not sms_actif():
        raise ErreurSMS("SMS non configurés (ORANGE_SMS_LOGIN / TOKEN / ACCESS_KEY absents)")
    destinataire = telephone.lstrip("+")
    propre = client is None
    client = client or httpx.Client(timeout=30, verify=settings.orange_sms_verify_ssl)
    ordre = ([_variante_retenue] if _variante_retenue is not None else []) + \
        [i for i in range(len(VARIANTES_CLE)) if i != _variante_retenue]
    try:
        erreur = None
        essais = 0
        for i in ordre:
            variante = VARIANTES_CLE[i]
            essais += 1
            try:
                r = _poster(client, variante, _champs(variante, destinataire, message, sujet))
            except httpx.HTTPError as e:
                # Cause exacte (certificat SSL refusé, délai dépassé, connexion refusée…)
                cause = str(e).strip() or e.__class__.__name__
                if "CERTIFICATE_VERIFY_FAILED" in cause or "SSL" in cause.upper():
                    cause += " — certificat du serveur Orange refusé (essayer ORANGE_SMS_VERIFY_SSL=False)"
                log.warning("SMS vers %s : échec de connexion à %s : %s", destinataire[:5] + "…", settings.orange_sms_base_url, cause)
                raise ErreurSMS(f"Orange SMS Pro injoignable : {e.__class__.__name__} : {cause[:300]}")
            erreur = _reponse_en_erreur(r)
            if not erreur:
                if _variante_retenue != i:
                    log.warning("SMS : combinaison acceptée par Orange = « %s »", variante[0])
                _variante_retenue = i
                log.info("SMS vers %s : HTTP %s %s", destinataire[:5] + "…", r.status_code, r.text[:1000])
                return r.text[:1000]
            code, _texte = erreur
            log.warning("SMS vers %s : combinaison « %s » refusée : HTTP %s %s",
                        destinataire[:5] + "…", variante[0], r.status_code, r.text[:600])
            if code != CODE_CLE_INVALIDE:
                break     # autre erreur que la clé : inutile d'essayer d'autres calculs
        message_erreur = erreur[1] if erreur else "Échec de l'envoi"
        if erreur and erreur[0] == CODE_CLE_INVALIDE:
            message_erreur += f" ({essais} façons de calculer la clé essayées — voir les logs)"
        raise ErreurSMS(message_erreur)
    finally:
        if propre:
            client.close()


def client_sms() -> httpx.Client:
    """Client HTTP réutilisable pour un envoi en série."""
    return httpx.Client(timeout=30, verify=settings.orange_sms_verify_ssl)


def message_identifiants(username: str, mot_de_passe: str) -> str:
    """Texte sans accents (alphabet GSM : 1 SMS = 160 caractères au lieu de 70)."""
    # Téléchargement de l'app mobile si configuré, sinon la plateforme
    lien = (settings.app_mobile_url or settings.app_url).rstrip("/") or "la plateforme eFlotte"
    return (
        f"eFlotte CAMUSAT: compte chauffeur cree. Lien: {lien} "
        f"Identifiant: {username} Mot de passe: {mot_de_passe} (a changer a la 1re connexion)"
    )
