from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .settings import Settings


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

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
    return True
