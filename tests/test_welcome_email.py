import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
import smtplib
from app.services.welcome_email import send_welcome_email


class WelcomeEmailTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(first_name='New',last_name='User',pharmacy_name='Test Pharmacy',email='new@example.com',role='nurse')
        self.settings = SimpleNamespace(smtp_host='smtp.gmail.com',smtp_port=587,smtp_from_email='sender@example.com',smtp_cc_email='copy@example.com',smtp_username='sender@example.com',smtp_password='private-secret',smtp_starttls=True,user_login_url='https://example.com/login')

    def test_addressing_tls_and_no_password(self):
        with patch('app.services.welcome_email.get_settings',return_value=self.settings), patch('app.services.welcome_email.smtplib.SMTP') as factory:
            smtp=factory.return_value.__enter__.return_value
            smtp.send_message.return_value={}
            self.assertEqual(send_welcome_email(self.user),'sent')
            smtp.starttls.assert_called_once()
            smtp.login.assert_called_once_with('sender@example.com','private-secret')
            message=smtp.send_message.call_args.args[0]
            self.assertEqual(message['To'],'new@example.com')
            self.assertEqual(message['Cc'],'copy@example.com')
            self.assertIn('https://example.com/login',message.get_content())
            self.assertNotIn('private-secret',message.as_string())

    def test_failure_returns_status(self):
        with patch('app.services.welcome_email.get_settings',return_value=self.settings), patch('app.services.welcome_email.smtplib.SMTP',side_effect=smtplib.SMTPException('secret response')):
            self.assertEqual(send_welcome_email(self.user),'failed')

    def test_missing_config_does_not_connect(self):
        self.settings.smtp_host=None
        with patch('app.services.welcome_email.get_settings',return_value=self.settings), patch('app.services.welcome_email.smtplib.SMTP') as factory:
            self.assertEqual(send_welcome_email(self.user),'not_configured')
            factory.assert_not_called()

    def test_partial_delivery(self):
        with patch('app.services.welcome_email.get_settings',return_value=self.settings), patch('app.services.welcome_email.smtplib.SMTP') as factory:
            factory.return_value.__enter__.return_value.send_message.return_value={'copy@example.com':(550,b'refused')}
            self.assertEqual(send_welcome_email(self.user),'partial')
