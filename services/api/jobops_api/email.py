from __future__ import annotations

import smtplib
import logging
from email.message import EmailMessage

from .settings import Settings


logger = logging.getLogger(__name__)


def send_invite_email(settings: Settings, *, to_email: str, invite_url: str) -> bool:
    if not settings.smtp_host or not settings.smtp_from_email:
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = to_email
    message["Subject"] = "Create your JobOps alpha account"
    message.set_content(
        "\n".join(
            [
                "You have been invited to create a JobOps alpha account.",
                "",
                f"Create your account here: {invite_url}",
                "",
                "This link expires and can only be used once.",
            ]
        )
    )

    return send_email_message(settings, message)


def send_password_reset_email(settings: Settings, *, to_email: str, reset_url: str) -> bool:
    if not settings.smtp_host or not settings.smtp_from_email:
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = to_email
    message["Subject"] = "Reset your JobOps alpha password"
    message.set_content(
        "\n".join(
            [
                "We received a request to reset your JobOps alpha password.",
                "",
                f"Reset your password here: {reset_url}",
                "",
                "This link expires and can only be used once. If you did not request it, you can ignore this email.",
            ]
        )
    )

    return send_email_message(settings, message)


def send_email_message(settings: Settings, message: EmailMessage) -> bool:
    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                if settings.smtp_username and settings.resend_api_key:
                    smtp.login(settings.smtp_username, settings.resend_api_key)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                smtp.starttls()
                if settings.smtp_username and settings.resend_api_key:
                    smtp.login(settings.smtp_username, settings.resend_api_key)
                smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as error:
        logger.warning("JobOps email delivery failed: %s", error.__class__.__name__)
        return False
