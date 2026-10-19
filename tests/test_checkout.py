import unittest
from uuid import uuid4
from datetime import date, timedelta
from unittest.mock import patch
from sqlalchemy import select, func
import test_auth as auth
from test_auth import SessionLocal
from app.models import Medicine, Customer, Prescription, Sale, StockMovement, PharmacistProfile
from app.models.sync import SyncOutbox

class CheckoutTests(unittest.TestCase):
    setUp=auth.AuthTests.setUp
    login=auth.AuthTests.login
    headers=auth.AuthTests.headers

    def seed(self, days=30, stock=5):
        with SessionLocal() as db:
            m=Medicine(name='Checkout medicine',sku=str(uuid4()),batch_number='TEST',expiry_date=date.today()+timedelta(days=days),purchase_price=2,selling_price=3.25,stock_quantity=stock)
            db.add(m);db.commit();return m.id

    def payload(self,mid):
        return dict(request_id=str(uuid4()),patient_name='Test Patient',prescribed_by='Dr Test',payment=dict(method='cash',tendered='10.00',confirmed=True),items=[dict(medicine_id=mid,quantity=2)])

    def test_checkout_atomic_and_retry_safe(self):
        headers=self.headers();mid=self.seed();p=self.payload(mid)
        result=self.client.post('/api/v1/sales/checkout',headers=headers,json=p)
        self.assertEqual(result.status_code,201,result.text)
        self.assertEqual(float(result.json()['total_amount']),6.5)
        replay=self.client.post('/api/v1/sales/checkout',headers=headers,json=p)
        self.assertEqual(replay.json()['id'],result.json()['id'])
        with SessionLocal() as db:
            self.assertEqual(db.get(Medicine,mid).stock_quantity,3)
            for model in [Customer,Prescription,Sale,StockMovement]:
                self.assertEqual(db.scalar(select(func.count()).select_from(model)),1)
            self.assertEqual(db.scalar(select(Prescription)).doctor_name,'Dr Test')
        p['patient_name']='Different patient'
        self.assertEqual(self.client.post('/api/v1/sales/checkout',headers=headers,json=p).status_code,409)

    def test_unavailable_stock_does_not_create_patient(self):
        headers=self.headers()
        for days,stock in [(-1,5),(30,1)]:
            response=self.client.post('/api/v1/sales/checkout',headers=headers,json=self.payload(self.seed(days,stock)))
            self.assertEqual(response.status_code,422,response.text)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Customer)),0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Sale)),0)

    def test_access_validation_and_doctor_suggestions(self):
        mid=self.seed();p=self.payload(mid)
        with SessionLocal() as db:
            db.get(PharmacistProfile,1).role='doctor';db.commit()
        headers=self.headers()
        self.assertEqual(self.client.post('/api/v1/sales/checkout',headers=headers,json=p).status_code,403)
        self.assertEqual(self.client.post('/api/v1/sales/checkout',json=p).status_code,401)
        self.assertTrue(self.client.get('/api/v1/sales/prescribers',headers=headers).json())
        with SessionLocal() as db:
            db.get(PharmacistProfile,1).role='pharmacist';db.commit()
        p['patient_name']=' '
        self.assertEqual(self.client.post('/api/v1/sales/checkout',headers=headers,json=p).status_code,422)

    def test_outbox_parent_order(self):
        from app.config import get_settings
        from app.models.sync import OfflineLease
        from datetime import datetime
        mid=self.seed();headers=self.headers()
        with SessionLocal() as db:
            db.add(OfflineLease(profile_id=1,cloud_employee_id=str(uuid4()),expires_at=datetime.utcnow()+timedelta(hours=12),last_observed_at=datetime.utcnow()));db.commit()
        with patch.object(get_settings(),'sync_enabled',True):
            result=self.client.post('/api/v1/sales/checkout',headers=headers,json=self.payload(mid))
        self.assertEqual(result.status_code,201,result.text)
        with SessionLocal() as db:
            self.assertEqual([o.entity for o in db.scalars(select(SyncOutbox).order_by(SyncOutbox.sequence))],['customers','prescriptions','sales'])

    def test_payment_validation_and_cash_change(self):
        headers=self.headers();mid=self.seed();payload=self.payload(mid)
        for payment in [dict(method='cash',tendered='1',confirmed=True),dict(method='upi',tendered='6.50',confirmed=True),dict(method='card',tendered='7',reference='terminal-1',confirmed=True),dict(method='cash',tendered='10',confirmed=False)]:
            payload['payment']=payment
            result=self.client.post('/api/v1/sales/checkout',headers=headers,json=payload)
            self.assertEqual(result.status_code,422,result.text)
        with SessionLocal() as db:
            self.assertEqual(db.get(Medicine,mid).stock_quantity,5)
            self.assertEqual(db.scalar(select(func.count()).select_from(Sale)),0)
        payload['payment']=dict(method='cash',tendered='10',confirmed=True)
        result=self.client.post('/api/v1/sales/checkout',headers=headers,json=payload)
        self.assertEqual(result.status_code,201,result.text)
        self.assertEqual(float(result.json()['payment']['change']),3.5)
        self.assertEqual(float(result.json()['payment']['amount']),6.5)
        replay=self.client.post('/api/v1/sales/checkout',headers=headers,json=payload)
        self.assertEqual(replay.json()['payment'],result.json()['payment'])
        listed=self.client.get('/api/v1/sales',headers=headers).json()
        self.assertEqual(listed[0]['payment'],result.json()['payment'])

    def test_digital_payment_reference_is_saved(self):
        headers=self.headers()
        for method in ['upi','card','bank_transfer']:
            payload=self.payload(self.seed())
            payload['payment']=dict(method=method,tendered='6.50',reference='TEST-TXN-123',confirmed=True)
            result=self.client.post('/api/v1/sales/checkout',headers=headers,json=payload)
            self.assertEqual(result.status_code,201,result.text)
            self.assertEqual(result.json()['payment']['method'],method)
            self.assertEqual(result.json()['payment']['reference'],'TEST-TXN-123')
            self.assertEqual(float(result.json()['payment']['change']),0)
