"""Welcome mail after a new account has been committed; never email credentials."""
from email.message import EmailMessage
import logging
import smtplib
import ssl
from urllib.parse import urlsplit
from app.config import get_settings

logger = logging.getLogger(__name__)


def send_welcome_email(user) -> str:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_from_email:
        return 'not_configured'
    try:
        message = EmailMessage()
        message['Subject'] = f'Welcome to {user.pharmacy_name}'
        message['From'] = settings.smtp_from_email
        message['To'] = user.email
        if settings.smtp_cc_email:
            message['Cc'] = settings.smtp_cc_email
        role = getattr(user.role, 'value', user.role)
        body = (f'Hello {user.first_name} {user.last_name},\n\n'
                f'Your account at {user.pharmacy_name} has been created.\n'
                f'Sign-in email: {user.email}\nRole: {role}\n\n')
        url = urlsplit(settings.user_login_url or '')
        if url.scheme in ('http', 'https') and url.netloc:
            body += f'Sign in: {settings.user_login_url}\n\n'
        body += ('Please contact your administrator for your initial password. '
                 'Passwords are never included in welcome emails.\n\n'
                 'If you were not expecting this account, contact your pharmacy administrator.')
        message.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or '')
            refused = smtp.send_message(message)
        if refused:
            return 'partial'
        return 'sent'
    except (OSError, smtplib.SMTPException, ValueError):
        # No addresses, credentials or SMTP server response bodies in logs.
        logger.warning('New-user welcome email delivery failed')
        return 'failed'
