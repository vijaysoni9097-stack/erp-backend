import unittest
from uuid import uuid4
from sqlalchemy import select,func
import test_auth as auth
import test_checkout as checkout
from test_auth import SessionLocal
from app.models import Customer,Prescription
from app.models.sync import SyncIdentity
from app.services.customer_mobile import normalize_mobile

class CustomerMobileTests(unittest.TestCase):
    setUp=auth.AuthTests.setUp
    login=auth.AuthTests.login
    headers=auth.AuthTests.headers
    seed=checkout.CheckoutTests.seed
    payload=checkout.CheckoutTests.payload

    def test_save_self_lookup_and_reuse(self):
        headers=self.headers();mid=self.seed(stock=10)
        p=self.payload(mid);p.pop('prescribed_by');p['customer_mobile']='98765 43210'
        response=self.client.post('/api/v1/sales/checkout',headers=headers,json=p)
        self.assertEqual(response.status_code,201,response.text)
        lookup=self.client.get('/api/v1/customers/lookup',headers=headers,params={'phone':'+91 98765 43210'})
        self.assertEqual(len(lookup.json()),1)
        self.assertEqual(lookup.json()[0]['full_name'],'Test Patient')
        self.assertEqual(lookup.json()[0]['phone'],'+919876543210')
        p['request_id']=str(uuid4());p['prescribed_by']='  '
        again=self.client.post('/api/v1/sales/checkout',headers=headers,json=p)
        self.assertEqual(again.status_code,201,again.text)
        self.assertEqual(again.json()['customer_id'],response.json()['customer_id'])
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Customer)),1)
            self.assertTrue(all(row.doctor_name=='self' for row in db.scalars(select(Prescription))))

    def test_shared_historical_numbers_and_deleted_exclusion(self):
        headers=self.headers()
        with SessionLocal() as db:
            a=Customer(full_name='First Person',phone='98765-43210');b=Customer(full_name='Second Person',phone='+91 (98765) 43210')
            removed=Customer(full_name='Removed',phone='9876543210')
            db.add_all([a,b,removed]);db.flush()
            db.add(SyncIdentity(entity='customers',local_id=removed.id,cloud_id=str(uuid4()),version=1,deleted=True));db.commit()
        response=self.client.get('/api/v1/customers/lookup',headers=headers,params={'phone':'00919876543210'})
        self.assertEqual({row['full_name'] for row in response.json()},{'First Person','Second Person'})
        self.assertEqual(self.client.get('/api/v1/customers/lookup',params={'phone':'9876543210'}).status_code,401)
        self.assertEqual(self.client.get('/api/v1/customers/lookup',headers=headers,params={'phone':'abc'}).status_code,422)

    def test_mobile_validation(self):
        self.assertEqual(normalize_mobile(''),None)
        self.assertEqual(normalize_mobile('+44 7700 900123'),'+447700900123')
        self.assertEqual(normalize_mobile('9876543210'),'+919876543210')
        for value in ['abc','123','+'+'1'*16]:
            with self.assertRaises(ValueError):normalize_mobile(value)
