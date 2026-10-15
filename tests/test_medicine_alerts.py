import unittest
from datetime import date, timedelta
import test_auth as auth
from test_auth import SessionLocal
from app.services.settings import get_pharmacy_preferences
from app.models.sync import SyncIdentity

class MedicineAlertsTests(unittest.TestCase):
    setUp=auth.AuthTests.setUp
    login=auth.AuthTests.login
    headers=auth.AuthTests.headers

    def test_create_and_expiry_boundaries(self):
        headers=self.headers()
        with SessionLocal() as db:
            prefs=get_pharmacy_preferences(db)
            prefs.expiry_alerts_enabled=True; prefs.expiry_alert_lead_days=30; db.commit()
        ids=[]
        for i,days in enumerate([-1,0,30,31]):
            payload=dict(name=f'Medicine {i}',sku=f'ALERT-{i}',batch_number='B',expiry_date=str(date.today()+timedelta(days=days)),purchase_price=1,selling_price=2)
            response=self.client.post('/api/v1/medicines',headers=headers,json=payload)
            self.assertEqual(response.status_code,201,response.text)
            ids.append(response.json()['id'])
        self.assertEqual(self.client.post('/api/v1/medicines',headers=headers,json=payload).status_code,409)
        result=self.client.get('/api/v1/medicines/expiry-alerts',headers=headers)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual([i['days_remaining'] for i in result.json()['items']],[-1,0,30])
        with SessionLocal() as db:
            db.add(SyncIdentity(entity='medicines',local_id=ids[0],cloud_id='deleted-test',deleted=True))
            db.commit()
        self.assertEqual(len(self.client.get('/api/v1/medicines/expiry-alerts',headers=headers).json()['items']),2)
        with SessionLocal() as db:
            get_pharmacy_preferences(db).expiry_alerts_enabled=False; db.commit()
        result=self.client.get('/api/v1/medicines/expiry-alerts',headers=headers).json()
        self.assertFalse(result['enabled']); self.assertEqual(result['items'],[])
