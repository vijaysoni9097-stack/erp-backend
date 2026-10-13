"""Isolated end-to-end tests; never connect to the user's local database."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from hashlib import sha256

_test_directory = TemporaryDirectory()
os.environ['DATABASE_URL'] = f"sqlite:///{Path(_test_directory.name) / 'auth.db'}"

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import AuthSession, PharmacistProfile, PasswordResetToken
from app.services.security import hash_secret
from app.services.settings import seed_settings
from app.setup_local import provision_account

PASSWORD = 'StrongPassword123!'


class AuthTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            seed_settings(db)
            provision_account(db, 'pharmacist@example.com', PASSWORD)
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)

    def login(self, email='pharmacist@example.com', password=PASSWORD):
        return self.client.post('/api/v1/auth/login', json={'email': email, 'password': password})

    def headers(self):
        return {'Authorization': 'Bearer ' + self.login().json()['access_token']}

    def test_login_me_logout_and_hashed_storage(self):
        response = self.login(' PHARMACIST@example.com ')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['success'])
        self.assertTrue(body['expires_at'].endswith('Z'))
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('password_hash', body['profile'])
        token = body['access_token']
        with SessionLocal() as db:
            session = db.scalar(select(AuthSession))
            self.assertEqual(session.token_hash, sha256(token.encode()).hexdigest())
        headers = {'Authorization': 'Bearer ' + token}
        self.assertEqual(self.client.get('/api/v1/auth/me', headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/v1/settings', headers=headers).status_code, 200)
        self.assertEqual(self.client.post('/api/v1/auth/logout', headers=headers).status_code, 204)
        self.assertEqual(self.client.get('/api/v1/auth/me', headers=headers).status_code, 401)

    def test_bad_credentials_and_literal_email_matching(self):
        for email, password in [('pharmacist@example.com', 'WrongPassword123!'),
                                ('missing@example.com', PASSWORD), ('%@example.com', PASSWORD)]:
            self.assertEqual(self.login(email, password).status_code, 401)
        self.assertEqual(self.client.post('/api/v1/auth/login', json={}).status_code, 422)

    def test_all_business_routes_are_protected(self):
        for route in app.routes:
            if route.path.startswith('/api/v1/') and '/auth/' not in route.path:
                for method in route.methods:
                    response = self.client.request(method, route.path.replace('{id}', '1'), json={})
                    self.assertEqual(response.status_code, 401, route.path)
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/auth/me', headers={'Authorization': 'Bearer invalid'}).status_code, 401)

    def test_expired_session(self):
        headers = self.headers()
        with SessionLocal() as db:
            db.scalar(select(AuthSession)).expires_at = datetime.now() - timedelta(days=1)
            db.commit()
        self.assertEqual(self.client.get('/api/v1/auth/me', headers=headers).status_code, 401)

    def test_password_change_revokes_all_sessions(self):
        first, second = self.headers(), self.headers()
        payload = {'current_password': PASSWORD, 'new_password': 'ReplacementPassword123!',
                   'confirm_password': 'ReplacementPassword123!'}
        self.assertEqual(self.client.post('/api/v1/settings/password', json=payload, headers=first).status_code, 204)
        for headers in (first, second):
            self.assertEqual(self.client.get('/api/v1/auth/me', headers=headers).status_code, 401)
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login(password=payload['new_password']).status_code, 200)

    def test_existing_short_password_can_login_and_be_changed(self):
        with SessionLocal() as db:
            db.get(PharmacistProfile, 1).password_hash = hash_secret('admin123')
            db.commit()
        response = self.login(password='admin123')
        self.assertEqual(response.status_code, 200)
        headers = {'Authorization': 'Bearer ' + response.json()['access_token']}
        response = self.client.post('/api/v1/settings/password', headers=headers, json={
            'current_password': 'admin123', 'new_password': PASSWORD, 'confirm_password': PASSWORD,
        })
        self.assertEqual(response.status_code, 204)

    def profile_payload(self, headers):
        data = self.client.get('/api/v1/settings/profile', headers=headers).json()
        return {key: value for key, value in data.items() if key not in ('id', 'role', 'created_at', 'updated_at')}

    def test_profile_photo_bio_persistence_and_removal(self):
        headers = self.headers()
        payload = self.profile_payload(headers)
        photo = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a4qkAAAAASUVORK5CYII='
        payload.update(professional_bio='Clinical pharmacist.', photo_data_url=photo)
        response = self.client.put('/api/v1/settings/profile', headers=headers, json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['role'], 'pharmacist')
        engine.dispose()
        saved = self.client.get('/api/v1/settings/profile', headers=headers).json()
        self.assertEqual(saved['professional_bio'], payload['professional_bio'])
        self.assertEqual(saved['photo_data_url'], photo)
        with SessionLocal() as db:
            self.assertEqual(db.get(PharmacistProfile, 1).photo_data_url, photo)
        payload['photo_data_url'] = None
        self.assertEqual(self.client.put('/api/v1/settings/profile', headers=headers, json=payload).status_code, 200)
        self.assertIsNone(self.client.get('/api/v1/settings/profile', headers=headers).json()['photo_data_url'])

    def test_profile_rejects_role_escalation_and_invalid_photo(self):
        headers = self.headers()
        payload = self.profile_payload(headers)
        for extra in ({'role': 'superadmin'}, {'photo_data_url': 'data:image/svg+xml;base64,PHN2Zz4='},
                      {'photo_data_url': 'data:image/png;base64,aGVsbG8='}, {'professional_bio': 'x' * 5001},
                      {'photo_data_url': 'x' * 2_800_001}):
            self.assertEqual(self.client.put('/api/v1/settings/profile', headers=headers,
                                            json={**payload, **extra}).status_code, 422)

    def test_profile_uses_authenticated_employee(self):
        with SessionLocal() as db:
            db.add(PharmacistProfile(id=2, first_name='Another', last_name='Employee',
                email='doctor@example.com', license_number='DOC-2', pharmacy_name='Clinic',
                role='doctor', password_hash=hash_secret(PASSWORD)))
            db.commit()
        token = self.login(email='doctor@example.com').json()['access_token']
        headers = {'Authorization': 'Bearer ' + token}
        payload = self.profile_payload(headers)
        payload['professional_bio'] = 'Doctor bio'
        self.assertEqual(self.client.put('/api/v1/settings/profile', headers=headers, json=payload).status_code, 200)
        with SessionLocal() as db:
            self.assertIsNone(db.get(PharmacistProfile, 1).professional_bio)
            self.assertEqual(db.get(PharmacistProfile, 2).professional_bio, 'Doctor bio')
        payload['email'] = 'PHARMACIST@example.com'
        self.assertEqual(self.client.put('/api/v1/settings/profile', headers=headers, json=payload).status_code, 409)

    def test_employee_upgrade_preserves_rows_and_session_foreign_key(self):
        from sqlalchemy import create_engine
        from app.migrations import migrate_employee_table
        legacy = create_engine('sqlite://')
        with legacy.begin() as conn:
            conn.exec_driver_sql('CREATE TABLE pharmacist_profiles (id INTEGER PRIMARY KEY, email TEXT, password_hash TEXT)')
            conn.exec_driver_sql("INSERT INTO pharmacist_profiles VALUES (1, 'existing@example.com', 'original-hash')")
            conn.exec_driver_sql('CREATE TABLE auth_sessions (id INTEGER PRIMARY KEY, profile_id INTEGER REFERENCES pharmacist_profiles(id), token_hash TEXT)')
            conn.exec_driver_sql("INSERT INTO auth_sessions VALUES (1, 1, 'original-token')")
        migrate_employee_table(legacy)
        migrate_employee_table(legacy)
        with legacy.connect() as conn:
            row = conn.exec_driver_sql('SELECT email, password_hash, role FROM employee_table').one()
            self.assertEqual(tuple(row), ('existing@example.com', 'original-hash', 'pharmacist'))
            self.assertEqual(inspect(conn).get_foreign_keys('auth_sessions')[0]['referred_table'], 'employee_table')
            self.assertEqual(conn.exec_driver_sql('PRAGMA foreign_key_check').all(), [])
        legacy.dispose()

    def request_reset(self, email='pharmacist@example.com'):
        return self.client.post('/api/v1/auth/forgot-password', json={'email': email})

    def complete_reset(self, token, password='ReplacementPassword123!'):
        return self.client.post('/api/v1/auth/reset-password', json={
            'token': token, 'new_password': password, 'confirm_password': password})

    @patch('app.services.password_reset.send_reset_email')
    def test_password_recovery(self, send):
        from app.config import get_settings
        settings = get_settings()
        with patch.object(settings, 'smtp_host', 'smtp.example.com'), \
             patch.object(settings, 'smtp_from_email', 'support@example.com'), \
             patch.object(settings, 'password_reset_url', 'https://example.com/reset-password'):
            headers = self.headers()
            response = self.request_reset(' PHARMACIST@example.com ')
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json(), self.request_reset('missing@example.com').json())
            token = send.call_args.args[1]
            self.request_reset()
            self.assertEqual(send.call_count, 1)
            with SessionLocal() as db:
                reset = db.scalar(select(PasswordResetToken))
                self.assertEqual(reset.token_hash, sha256(token.encode()).hexdigest())
            self.assertEqual(self.complete_reset('x' * 43).status_code, 400)
            self.assertEqual(self.complete_reset(token, 'short').status_code, 422)
            self.assertEqual(self.complete_reset(token).status_code, 204)
            self.assertEqual(self.complete_reset(token).status_code, 400)
            self.assertEqual(self.client.get('/api/v1/auth/me', headers=headers).status_code, 401)
            self.assertEqual(self.login().status_code, 401)
            self.assertEqual(self.login(password='ReplacementPassword123!').status_code, 200)

    @patch('app.services.password_reset.send_reset_email')
    def test_reset_expiry_password_change_and_delivery_failure(self, send):
        from app.config import get_settings
        settings = get_settings()
        with patch.object(settings, 'smtp_host', 'smtp.example.com'), \
             patch.object(settings, 'smtp_from_email', 'support@example.com'), \
             patch.object(settings, 'password_reset_url', 'https://example.com/reset-password'):
            self.request_reset()
            first = send.call_args.args[1]
            with SessionLocal() as db:
                row = db.scalar(select(PasswordResetToken))
                row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
                row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=20)
                db.commit()
            self.assertEqual(self.complete_reset(first).status_code, 400)
            self.request_reset()
            second = send.call_args.args[1]
            self.assertEqual(self.complete_reset(first).status_code, 400)
            headers = self.headers()
            self.client.post('/api/v1/settings/password', headers=headers, json={
                'current_password': PASSWORD, 'new_password': 'ChangedPassword123!',
                'confirm_password': 'ChangedPassword123!'})
            self.assertEqual(self.complete_reset(second).status_code, 400)
            with SessionLocal() as db:
                db.scalar(select(PasswordResetToken)).created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2)
                db.commit()
            send.side_effect = OSError('Delivery failed')
            self.assertEqual(self.request_reset().status_code, 202)
            self.assertEqual(self.request_reset('missing@example.com').status_code, 202)

    @patch('app.services.password_reset.smtplib.SMTP')
    def test_reset_email_uses_tls_and_frontend_link(self, smtp):
        from app.config import get_settings
        from app.services.password_reset import send_reset_email
        settings = get_settings()
        with patch.object(settings, 'smtp_host', 'smtp.example.com'), \
             patch.object(settings, 'smtp_from_email', 'support@example.com'), \
             patch.object(settings, 'smtp_username', 'mail-user'), \
             patch.object(settings, 'smtp_password', 'mail-secret'), \
             patch.object(settings, 'smtp_starttls', True), \
             patch.object(settings, 'password_reset_url', 'https://example.com/reset?lang=en&token=old'):
            send_reset_email('pharmacist@example.com', 'new-token')
        connection = smtp.return_value.__enter__.return_value
        connection.starttls.assert_called_once()
        connection.login.assert_called_once_with('mail-user', 'mail-secret')
        message = connection.send_message.call_args.args[0]
        self.assertEqual(message['To'], 'pharmacist@example.com')
        self.assertIn('https://example.com/reset?lang=en&token=new-token', message.get_content())
        self.assertNotIn('token=old', message.get_content())

    def test_recovery_requires_configuration(self):
        from app.config import get_settings
        with patch.object(get_settings(), 'smtp_host', None):
            self.assertEqual(self.request_reset().status_code, 503)
            self.assertEqual(self.request_reset('missing@example.com').status_code, 503)

    def test_setup_cannot_replace_account(self):
        with SessionLocal() as db:
            with self.assertRaises(ValueError):
                provision_account(db, 'other@example.com', 'ReplacementPassword123!')
        self.assertEqual(self.login().status_code, 200)

    def test_tables_and_restart_persistence(self):
        headers = self.headers()
        self.assertIn('auth_sessions', inspect(engine).get_table_names())
        engine.dispose()
        with TestClient(app) as restarted:
            self.assertEqual(restarted.get('/api/v1/auth/me', headers=headers).status_code, 200)


if __name__ == '__main__':
    unittest.main()
