"""User-management API tests using the isolated auth test database."""
import unittest
from unittest.mock import patch
import test_auth as auth
from test_auth import SessionLocal, PASSWORD
from app.models import PharmacistProfile, PasswordResetToken
from app.models.settings import EmployeeRole
from app.services.security import verify_secret
from datetime import datetime, timedelta


class UserAdminTests(unittest.TestCase):
    setUp = auth.AuthTests.setUp
    login = auth.AuthTests.login
    headers = auth.AuthTests.headers

    def admin_headers(self):
        with SessionLocal() as db:
            db.get(PharmacistProfile, 1).role = EmployeeRole.superadmin
            db.commit()
        return self.headers()

    def create(self, headers, **changes):
        payload = dict(first_name='Test', last_name='User', email='other@example.com',
                       license_number='TEST-2', pharmacy_name='Test Pharmacy', role='nurse',
                       password=PASSWORD)
        payload.update(changes)
        return self.client.post('/api/v1/users', headers=headers, json=payload)

    def test_welcome_failure_keeps_user_and_duplicate_does_not_email(self):
        headers = self.admin_headers()
        with patch('app.services.welcome_email.send_welcome_email', return_value='failed') as send:
            response = self.create(headers)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()['welcome_email_status'], 'failed')
            self.assertEqual(self.create(headers).status_code, 409)
            send.assert_called_once()
        self.assertEqual(len(self.client.get('/api/v1/users', headers=headers).json()), 2)

    def test_permissions(self):
        routes = [('get', '/api/v1/users', None), ('post', '/api/v1/users', {}),
                  ('delete', '/api/v1/users/2', None), ('post', '/api/v1/users/2/reset-password', {})]
        for role in ['doctor', 'admin', 'pharmacist', 'nurse', 'receptionist']:
            with SessionLocal() as db:
                db.get(PharmacistProfile, 1).role = EmployeeRole(role)
                db.commit()
            headers = self.headers()
            for method, path, body in routes:
                kwargs = {'json': body} if body is not None else {}
                self.assertEqual(self.client.request(method, path, headers=headers, **kwargs).status_code, 403)
                self.assertEqual(self.client.request(method, path, **kwargs).status_code, 401)

    def test_create_reset_delete(self):
        headers = self.admin_headers()
        response = self.create(headers)
        self.assertEqual(response.status_code, 201, response.text)
        user = response.json()
        self.assertNotEqual(user['id'], 1)
        self.assertNotIn('password_hash', user)
        self.assertNotIn('password', user)
        self.assertEqual(len(self.client.get('/api/v1/users', headers=headers).json()), 2)
        self.assertEqual(self.create(headers).status_code, 409)
        login = self.login(email=user['email']).json()
        old_headers = {'Authorization': 'Bearer ' + login['access_token']}
        with SessionLocal() as db:
            self.assertTrue(verify_secret(PASSWORD, db.get(PharmacistProfile, user['id']).password_hash))
            db.add(PasswordResetToken(profile_id=user['id'], token_hash='x'*64, password_hash_at_issue='old', created_at=datetime.now(), expires_at=datetime.now()+timedelta(minutes=15)))
            db.commit()
        url = f"/api/v1/users/{user['id']}/reset-password"
        self.assertEqual(self.client.post(url, headers=headers, json={'new_password': 'short', 'confirm_password': 'short'}).status_code, 422)
        self.assertEqual(self.client.post(url, headers=headers, json={'new_password': PASSWORD, 'confirm_password': 'DifferentPassword123!'}).status_code, 422)
        new = 'ReplacementPassword123!'
        self.assertEqual(self.client.post(url, headers=headers, json={'new_password': new, 'confirm_password': new}).status_code, 204)
        self.assertEqual(self.client.get('/api/v1/auth/me', headers=old_headers).status_code, 401)
        self.assertEqual(self.login(email=user['email']).status_code, 401)
        renewed = self.login(email=user['email'], password=new)
        self.assertEqual(renewed.status_code, 200)
        with SessionLocal() as db:
            self.assertEqual(db.query(PasswordResetToken).count(), 0)
        self.assertEqual(self.client.delete(f"/api/v1/users/{user['id']}", headers=headers).status_code, 204)
        self.assertEqual(self.login(email=user['email'], password=new).status_code, 401)
        self.assertEqual(self.client.get('/api/v1/auth/me', headers={'Authorization': 'Bearer '+renewed.json()['access_token']}).status_code, 401)
        self.assertEqual(self.client.delete(f"/api/v1/users/{user['id']}", headers=headers).status_code, 404)

    def test_protected_admin_and_self(self):
        headers = self.admin_headers()
        response = self.client.delete('/api/v1/users/1', headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail'], 'You cannot delete your own account')
        self.assertEqual(self.client.get('/api/v1/auth/me', headers=headers).status_code, 200)
        with SessionLocal() as db:
            self.assertIsNotNone(db.get(PharmacistProfile, 1))
        self.assertEqual(self.client.post('/api/v1/users/1/reset-password', headers=headers, json={'new_password': PASSWORD, 'confirm_password': PASSWORD}).status_code, 400)
        other = self.create(headers, role='superadmin').json()
        self.assertEqual(self.client.delete(f"/api/v1/users/{other['id']}", headers=headers).status_code, 403)
        self.assertEqual(self.create(headers, role='invalid').status_code, 422)
