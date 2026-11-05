"""
Envoi d'e-mails (SMTP, port 587 + STARTTLS par défaut) — mêmes variables que la plateforme eRH :
EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_USE_TLS, EMAIL_FROM.
Sans EMAIL_HOST, les e-mails sont désactivés (un avertissement est écrit dans les logs).
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from ..config import settings

log = logging.getLogger("eflotte.email")


class ErreurEmail(Exception):
    pass


def email_actif() -> bool:
    return bool(settings.email_host and (settings.email_from or settings.email_host_user))


def envoyer_email(destinataires: list[str], sujet: str, texte: str, contenu_html: str | None = None) -> None:
    destinataires = [d.strip() for d in destinataires if d and d.strip()]
    if not destinataires:
        raise ErreurEmail("Aucun destinataire")
    if not email_actif():
        raise ErreurEmail("E-mails non configurés (EMAIL_HOST absent du .env)")
    expediteur = settings.email_from or settings.email_host_user
    msg = EmailMessage()
    msg["Subject"] = sujet
    msg["From"] = formataddr(("eFlotte Camusat", expediteur))
    msg["To"] = ", ".join(destinataires)
    msg.set_content(texte)
    if contenu_html:
        msg.add_alternative(contenu_html, subtype="html")
    try:
        with smtplib.SMTP(settings.email_host, settings.email_port, timeout=20) as smtp:
            if settings.email_use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.email_host_user:
                smtp.login(settings.email_host_user, settings.email_host_password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise ErreurEmail("Connexion SMTP refusée (EMAIL_HOST_USER / EMAIL_HOST_PASSWORD)")
    except (OSError, smtplib.SMTPException) as e:
        raise ErreurEmail(f"Envoi impossible : {e.__class__.__name__} : {str(e)[:200]}")
    log.info("E-mail « %s » envoyé à %s", sujet, ", ".join(destinataires))
