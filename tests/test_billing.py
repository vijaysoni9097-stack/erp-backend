import unittest
import test_auth as auth
from test_auth import SessionLocal
from app.models import PharmacistProfile
from app.models.settings import EmployeeRole

class BillingTests(unittest.TestCase):
    setUp = auth.AuthTests.setUp
    login = auth.AuthTests.login
    headers = auth.AuthTests.headers

    def test_gstin_permissions_format_and_persistence(self):
        self.assertEqual(self.client.get('/api/v1/settings/billing').status_code,401)
        headers=self.headers()
        self.assertEqual(self.client.get('/api/v1/settings/billing',headers=headers).json(),{'gstin':None})
        self.assertEqual(self.client.put('/api/v1/settings/billing',headers=headers,json={'gstin':'27ABCDE1234F1Z5'}).status_code,403)
        with SessionLocal() as db:
            db.get(PharmacistProfile,1).role=EmployeeRole.superadmin;db.commit()
        headers=self.headers()
        self.assertEqual(self.client.put('/api/v1/settings/billing',headers=headers,json={'gstin':'bad'}).status_code,422)
        result=self.client.put('/api/v1/settings/billing',headers=headers,json={'gstin':' 27abcde1234f1z5 '})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['gstin'],'27ABCDE1234F1Z5')
        self.assertEqual(self.client.get('/api/v1/settings/billing',headers=headers).json(),result.json())
        self.assertEqual(self.client.put('/api/v1/settings/billing',headers=headers,json={'gstin':''}).json(),{'gstin':None})
