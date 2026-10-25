import unittest
from unittest.mock import patch
import test_auth as auth
from app.config import Settings


class OnlineOnlyTests(unittest.TestCase):
    setUp = auth.AuthTests.setUp
    login = auth.AuthTests.login
    headers = auth.AuthTests.headers

    def test_sync_routes_removed(self):
        headers = self.headers()
        for path in ('/api/v1/sync/status', '/api/v1/sync/wake', '/api/v1/sync/login'):
            self.assertEqual(self.client.post(path, json={}, headers=headers).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/sync/status', headers=headers).status_code, 404)

    def test_legacy_sync_setting_ignored(self):
        with patch.dict('os.environ', {'SYNC_ENABLED':'true'}):
            settings = Settings(_env_file=None)
        self.assertNotIn('sync_enabled', settings.model_dump())
